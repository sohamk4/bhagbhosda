from __future__ import annotations

from datetime import date, timedelta

from .simulation import simulate_plan


class PaymentPlanEngine:

    def __init__(self, services):
        self.services = services

    # ==========================================================
    # TOP-LEVEL — mostly unchanged
    # ==========================================================

    def evaluate(self, user_id: str, request_id: str,spending_changes: list[dict] | None = None,) -> dict:
        request = self._get_request(request_id)
        profile = self.services.profile.get_profile(user_id)
        if profile is None:
            raise ValueError(f"Profile not found: {user_id}")

        forecast = self._forecast(user_id, request_id, spending_changes=spending_changes)

        options = self.services.payment_options.get_payment_options(request_id)

        # FIX B5 — accept either column name.
        accepted_methods = set(
            profile.get("payment_methods_user_will_consider")
            or profile.get("accepted_payment_methods")
            or []
        )

        eligible_options = [
            opt for opt in options
            if opt["payment_method"] in accepted_methods
        ]

        evaluated = []
        for opt in eligible_options:
            evaluated.append(self._evaluate_option(
                request=request,
                profile=profile,
                forecast=forecast,
                option=opt,
            ))

        partial = self._evaluate_partial_payment(
            request=request,
            profile=profile,
            forecast=forecast,
        )
        if partial is not None:
            evaluated.append(partial)

        # FIX B3 — require BOTH safe and completes_by_deadline.
        viable = [
            opt for opt in evaluated
            if opt["safe"] and opt["completes_by_deadline"]
        ]

        viable.sort(key=self._ranking_key)

        return {
            "request_id": request_id,
            "accepted_payment_methods": sorted(accepted_methods),
            "eligible_options": evaluated,
            "viable_options": viable,
            # FIX B4 — explicit None is fine here; orchestrator decides
            # fallback (wait / not_recommended) based on affordability.
            "recommended_option": viable[0] if viable else None,
        }

    # ==========================================================
    # OPTION EVAL — now uses shared simulate_plan
    # ==========================================================

    def _evaluate_option(
        self,
        request: dict,
        profile: dict,
        forecast: dict,
        option: dict,
    ) -> dict:
        payments = self._build_payments(option)
        last_payment_date = payments[-1]["date"]

        completes_by_deadline = (
            last_payment_date <= request["desired_completion_date"]
        )

        sim = simulate_plan(
            starting_balance=float(profile["current_available_balance"]),
            minimum_balance=float(profile["minimum_balance_to_keep"]),
            projected_events=forecast["projected_events"],
            payments=payments,
            forecast_start=forecast["forecast_start"],
            forecast_end=forecast["forecast_end"],
        )

        return {
            **option,
            "safe": sim["safe"],
            "completes_by_deadline": completes_by_deadline,
            "requires_spending_changes": False,
            "last_payment_date": last_payment_date,
            "payment_plan": self._format_payment_plan(payments),
            "recommended_payment_method": option["payment_method"],
            "number_of_payments": option["number_of_payments"],
        }

    # ==========================================================
    # BUILD INSTALLMENT PAYMENTS — unchanged
    # ==========================================================

    def _build_payments(self, option: dict) -> list[dict]:
        first = date.fromisoformat(option["first_payment_date"])
        interval = int(option.get("payment_frequency_days") or 0)
        n = int(option["number_of_payments"])
        amount = float(option["payment_amount"])

        return [
            {
                "date": (first + timedelta(days=interval * i)).isoformat(),
                "amount": amount,
            }
            for i in range(n)
        ]

    # ==========================================================
    # PARTIAL PAYMENT — rewritten (FIX B1 + B2)
    # ==========================================================

    def _evaluate_partial_payment(
        self,
        request: dict,
        profile: dict,
        forecast: dict,
    ) -> dict | None:
        if not self._as_bool(request.get("allows_partial_payment")):
            return None

        request_date = request["request_date"]
        requested_amount = float(request["requested_amount"])
        deadline = request["desired_completion_date"]
        current_balance = float(profile["current_available_balance"])
        minimum_balance = float(profile["minimum_balance_to_keep"])

        # --------------------------------------------------
        # FIX B1 — the first payment amount must be safe
        # *given that a second payment is coming later*.
        #
        # We binary-search the first payment X, and for each X
        # check whether a valid D exists. Feasible(X) is not
        # strictly monotonic, but the *upper* bound for X is
        # the max safe single payment today. Empirically the
        # smallest X that still leaves a valid D is X = the
        # max safe single payment; smaller X only makes the
        # second payment bigger. So: try X = max_safe, then
        # walk down if it fails.
        # --------------------------------------------------
        max_first = self._max_safe_single_payment(
            forecast=forecast,
            current_balance=current_balance,
            minimum_balance=minimum_balance,
            requested_amount=requested_amount,
            request_date=request_date,
        )

        if max_first <= 0:
            return None
        if max_first >= requested_amount - 1e-6:
            return None  # fully payable today; not a partial case

        # FIX B2 — for each candidate X, find the earliest D
        # such that the *two-payment plan* [today: X, D: P-X]
        # is safe.
        MAX_PARTIAL_ATTEMPTS = 20
        attempts = 0
        
        candidate_first = max_first
        
        while candidate_first > 0.01 and attempts < MAX_PARTIAL_ATTEMPTS:
            attempts += 1
            remaining = requested_amount - candidate_first
            d = self._earliest_second_payment_date(
                forecast=forecast,
                current_balance=current_balance,
                minimum_balance=minimum_balance,
                first_amount=candidate_first,
                remaining_amount=remaining,
                request_date=request_date,
                deadline=deadline,
            )
            if d is not None:
                payments = [
                    {"date": request_date, "amount": candidate_first},
                    {"date": d, "amount": remaining},
                ]

                sim = simulate_plan(
                    starting_balance=current_balance,
                    minimum_balance=minimum_balance,
                    projected_events=forecast["projected_events"],
                    payments=payments,
                    forecast_start=forecast["forecast_start"],
                    forecast_end=forecast["forecast_end"],
                )

                if sim["safe"]:
                    return {
                        "payment_option_id": "zzz_partial_payment",
                        "request_id": request["request_id"],
                        "payment_method": "partial_payment",
                        "payment_amount": round(candidate_first, 2),
                        "number_of_payments": 2,
                        "first_payment_date": request_date,
                        "payment_frequency_days": None,
                        "financing_fee": 0.0,
                        "total_payable_amount": requested_amount,
                        "safe": True,
                        "completes_by_deadline": d <= deadline,
                        "requires_spending_changes": False,
                        "last_payment_date": d,
                        "payment_plan": self._format_payment_plan(payments),
                        "recommended_payment_method": "partial_payment",
                    }

            # Reduce the first payment by 5% and retry.
            candidate_first = round(candidate_first * 0.95, 2)

        return None

    def _earliest_second_payment_date(
        self,
        forecast: dict,
        current_balance: float,
        minimum_balance: float,
        first_amount: float,
        remaining_amount: float,
        request_date: str,
        deadline: str,
    ) -> str | None:
        start = date.fromisoformat(request_date) + timedelta(days=1)
        end = date.fromisoformat(deadline)

        current = start
        while current <= end:
            payments = [
                {"date": request_date, "amount": first_amount},
                {"date": current.isoformat(), "amount": remaining_amount},
            ]
            sim = simulate_plan(
                starting_balance=current_balance,
                minimum_balance=minimum_balance,
                projected_events=forecast["projected_events"],
                payments=payments,
                forecast_start=forecast["forecast_start"],
                forecast_end=forecast["forecast_end"],
            )
            if sim["safe"]:
                return current.isoformat()
            current += timedelta(days=1)

        return None

    def _max_safe_single_payment(
        self,
        forecast: dict,
        current_balance: float,
        minimum_balance: float,
        requested_amount: float,
        request_date: str,
    ) -> float:
        upper = min(
            max(0.0, current_balance - minimum_balance),
            requested_amount,
        )
        if upper <= 0:
            return 0.0

        low, high = 0.0, upper
        for _ in range(50):
            mid = (low + high) / 2
            sim = simulate_plan(
                starting_balance=current_balance,
                minimum_balance=minimum_balance,
                projected_events=forecast["projected_events"],
                payments=[{"date": request_date, "amount": mid}],
                forecast_start=forecast["forecast_start"],
                forecast_end=forecast["forecast_end"],
            )
            if sim["safe"]:
                low = mid
            else:
                high = mid

        return round(low, 2)

    # ==========================================================
    # FORMAT + RANK — unchanged except ID sorting
    # ==========================================================

    @staticmethod
    def _format_payment_plan(payments: list[dict]) -> str:
        parts = []
        for p in payments:
            amt = float(p["amount"])
            if amt.is_integer():
                amt_s = str(int(amt))
            else:
                amt_s = f"{amt:.2f}".rstrip("0").rstrip(".")
            parts.append(f"{p['date']}:{amt_s}")
        return "|".join(parts)

    @staticmethod
    def _ranking_key(result: dict):
        return (
            not result["completes_by_deadline"],
            result["requires_spending_changes"],
            float(result["total_payable_amount"]),
            result["first_payment_date"],
            int(result["number_of_payments"]),
            str(result["payment_option_id"]),
        )

    @staticmethod
    def _as_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ("true", "1", "yes", "y")

    # ==========================================================
    # SERVICES
    # ==========================================================

    def _forecast(self, user_id, request_id, spending_changes: list[dict] | None = None,):
        from .forecast import ForecastEngine
        return ForecastEngine(self.services).forecast(
            user_id,
            request_id,
            spending_changes=spending_changes,    
            currency_converter=getattr(
                self.services.exchange_rates, "converter", None
            ),
        )

    def _get_request(self, request_id: str) -> dict:
        request = self.services.requests.get_request(request_id)
        if request is None:
            raise ValueError(f"Request not found: {request_id}")
        return request