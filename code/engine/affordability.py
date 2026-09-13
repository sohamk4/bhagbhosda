from __future__ import annotations

from datetime import date, timedelta

from .simulation import simulate_plan


class AffordabilityEngine:
    """
    Computes financial capacity for a request, independent of the user's
    payment-method preferences. Produces the raw facts; an orchestrator
    assigns the final affordability_status using preference + plan info.
    """

    def __init__(self, services):
        self.services = services

    def evaluate(self, user_id: str, request_id: str,spending_changes: list[dict] | None = None,) -> dict:
        request = self._get_request(request_id)
        profile = self.services.profile.get_profile(user_id)
        if profile is None:
            raise ValueError(f"Profile not found: {user_id}")

        # FIX A4 — pass through currency converter so multi-currency
        # users are not summed in mixed units.
        forecast = self._forecast(user_id, request_id,spending_changes=spending_changes)

        request_date = request["request_date"]
        requested_amount = float(request["requested_amount"])
        current_balance = float(profile["current_available_balance"])
        minimum_balance = float(profile["minimum_balance_to_keep"])

        # ------------------------------------------------------
        # FIX A1 — amount_safe_to_pay is the max single payment
        # today that keeps the FULL 90-day trajectory safe.
        # ------------------------------------------------------
        amount_safe = self._max_safe_single_payment(
            forecast=forecast,
            current_balance=current_balance,
            minimum_balance=minimum_balance,
            requested_amount=requested_amount,
            request_date=request_date,
        )

        # ------------------------------------------------------
        # FIX A2 — earliest_date is the first day D such that
        # paying the full amount on D keeps the 90-day trajectory
        # (including days after D) safe.
        # ------------------------------------------------------
        earliest = self._earliest_full_payment_date(
            forecast=forecast,
            current_balance=current_balance,
            minimum_balance=minimum_balance,
            requested_amount=requested_amount,
            request_date=request_date,
        )

        # ------------------------------------------------------
        # Financial status — orchestrator may downgrade to
        # affordable_with_plan based on available plans.
        # ------------------------------------------------------
        if earliest == request_date:
            status = "affordable_now"
        elif earliest is not None:
            status = "affordable_later"
        else:
            status = "not_affordable"

        return {
            "request_id": request_id,
            "request_date": request_date,
            "requested_amount": requested_amount,
            "amount_safe_to_pay": amount_safe,
            "affordability_status": status,
            # FIX A5 — empty string, not "none".
            "earliest_date_for_full_payment": earliest or "",
            # FIX A6 — spending changes are computed elsewhere; this
            # engine returns the raw financial fact.
            "spending_changes_needed": "none",
            "forecast_safe": forecast["forecast_safe"],
            "minimum_projected_balance": forecast["minimum_projected_balance"],
            "_forecast": forecast,   # pass to plan engine to avoid re-running
        }

    # ==========================================================
    # CORE COMPUTATION
    # ==========================================================

    def _max_safe_single_payment(
        self,
        forecast: dict,
        current_balance: float,
        minimum_balance: float,
        requested_amount: float,
        request_date: str,
    ) -> float:
        # Upper bound: can't drop below min today, and can't exceed request.
        upper = min(
            max(0.0, current_balance - minimum_balance),
            requested_amount,
        )
        if upper <= 0:
            return 0.0

        low, high = 0.0, upper
        for _ in range(50):
            mid = (low + high) / 2
            result = simulate_plan(
                starting_balance=current_balance,
                minimum_balance=minimum_balance,
                projected_events=forecast["projected_events"],
                payments=[{"date": request_date, "amount": mid}],
                forecast_start=forecast["forecast_start"],
                forecast_end=forecast["forecast_end"],
            )
            if result["safe"]:
                low = mid
            else:
                high = mid

        return round(low, 2)

    def _earliest_full_payment_date(
        self,
        forecast: dict,
        current_balance: float,
        minimum_balance: float,
        requested_amount: float,
        request_date: str,
    ) -> str | None:
        start = date.fromisoformat(request_date)
        end = date.fromisoformat(forecast["forecast_end"])

        current = start
        while current <= end:
            result = simulate_plan(
                starting_balance=current_balance,
                minimum_balance=minimum_balance,
                projected_events=forecast["projected_events"],
                payments=[{
                    "date": current.isoformat(),
                    "amount": requested_amount,
                }],
                forecast_start=forecast["forecast_start"],
                forecast_end=forecast["forecast_end"],
            )
            if result["safe"]:
                return current.isoformat()
            current += timedelta(days=1)

        return None

    # ==========================================================
    # SERVICES
    # ==========================================================

    def _forecast(self, user_id: str, request_id: str, spending_changes: list[dict] | None = None,) -> dict:
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