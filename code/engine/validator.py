# engine/validator.py

from __future__ import annotations

from datetime import date


class DecisionValidator:
    """
    Enforces structural, range, and cross-field invariants on a decision
    row before it's written to output.csv.

    Usage:
        result = validator.validate(decision, request)
        if not result["valid"]:
            for e in result["errors"]:
                print(e)
    """

    REQUIRED_FIELDS = {
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    }

    VALID_STATUSES = {
        "affordable_now",
        "affordable_with_plan",
        "affordable_later",
        "not_affordable",
    }

    VALID_METHODS = {
        "full_payment",
        "partial_payment",
        "installments",
        "wait",
        "not_recommended",
    }

    # Status -> methods that may legally accompany it.
    STATUS_METHOD_COMPAT = {
        "affordable_now": {"full_payment"},
        "affordable_with_plan": {
            "full_payment",
            "partial_payment",
            "installments",
        },
        "affordable_later": {"wait"},
        "not_affordable": {"not_recommended"},
    }

    # ==========================================================
    # PUBLIC
    # ==========================================================

    def validate(
        self,
        decision: dict,
        request: dict,
        payment_options: list[dict] | None = None,
        events: list[dict] | None = None,
    ) -> dict:
        """
        payment_options: optional, from `request_payment_options.csv`
                         for the request. Enables exact-match check
                         on installment plans.
        events:          optional, full event list for the user.
                         Enables flexible-recurring check on
                         `spending_changes_needed`.
        """
        errors: list[str] = []

        # ------------------------------------------------------
        # 1. Required fields
        # ------------------------------------------------------
        missing = self.REQUIRED_FIELDS - set(decision.keys())
        if missing:
            errors.append(f"missing_fields:{sorted(missing)}")

        # ------------------------------------------------------
        # 2. Request context
        # ------------------------------------------------------
        try:
            request_date = date.fromisoformat(request["request_date"])
            requested_amount = float(request["requested_amount"])
            desired_date = date.fromisoformat(
                request["desired_completion_date"]
            )
            allows_partial = self._as_bool(
                request.get("allows_partial_payment")
            )
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "valid": False,
                "errors": [f"bad_request:{exc}"],
                "decision": decision,
            }

        # ------------------------------------------------------
        # 3. amount_safe_to_pay — numeric, in range
        # ------------------------------------------------------
        amount = decision.get("amount_safe_to_pay")
        amount_ok = False
        if amount is None:
            errors.append("amount_safe_to_pay_missing")
        else:
            try:
                amount = float(amount)
                if amount < 0:
                    errors.append("amount_safe_to_pay_negative")
                elif amount > requested_amount:
                    errors.append("amount_safe_to_pay_exceeds_requested")
                else:
                    amount_ok = True
            except (ValueError, TypeError):
                errors.append("amount_safe_to_pay_not_numeric")

        # ------------------------------------------------------
        # 4. Enums
        # ------------------------------------------------------
        status = decision.get("affordability_status")
        if status not in self.VALID_STATUSES:
            errors.append(f"invalid_status:{status}")

        method = decision.get("recommended_payment_method")
        if method not in self.VALID_METHODS:
            errors.append(f"invalid_method:{method}")

        # ------------------------------------------------------
        # 5. Status <-> method compatibility
        # ------------------------------------------------------
        if status in self.VALID_STATUSES and method in self.VALID_METHODS:
            allowed = self.STATUS_METHOD_COMPAT[status]
            if method not in allowed:
                errors.append(
                    f"incompatible_status_method:{status}/{method}"
                )

        # ------------------------------------------------------
        # 6. affordable_now -> earliest == request_date
        # ------------------------------------------------------
        earliest = decision.get("earliest_date_for_full_payment")

        if status == "affordable_now":
            if earliest != request["request_date"]:
                errors.append(
                    "affordable_now_requires_earliest_eq_request_date"
                )
            if amount_ok and amount < requested_amount - 1e-6:
                errors.append(
                    "affordable_now_requires_amount_eq_requested"
                )

        # ------------------------------------------------------
        # 7. earliest_date parsing and range
        # ------------------------------------------------------
        earliest_parsed = None
        if earliest not in (None, "", "none", "None"):
            try:
                earliest_parsed = date.fromisoformat(str(earliest))
                if earliest_parsed < request_date:
                    errors.append("earliest_date_before_request_date")
            except ValueError:
                errors.append(f"invalid_earliest_date:{earliest}")

        # ------------------------------------------------------
        # 8. payment_plan parsing
        # ------------------------------------------------------
        plan, plan_errors = self._parse_plan(
            decision.get("payment_plan")
        )
        errors.extend(plan_errors)

        # ------------------------------------------------------
        # 9. Method-specific plan rules
        # ------------------------------------------------------
        if not plan_errors:
            errors.extend(
                self._check_plan_shape(
                    plan=plan,
                    method=method,
                    status=status,
                    request_date=request_date,
                    requested_amount=requested_amount,
                    amount_safe_to_pay=amount if amount_ok else None,
                    earliest_parsed=earliest_parsed,
                    payment_options=payment_options or [],
                )
            )

        # ------------------------------------------------------
        # 10. Partial payment preconditions
        # ------------------------------------------------------
        if method == "partial_payment":
            if not allows_partial:
                errors.append("partial_payment_not_allowed_by_request")
            if status != "affordable_with_plan":
                errors.append(
                    "partial_payment_requires_affordable_with_plan"
                )

        # ------------------------------------------------------
        # 11. spending_changes_needed parsing
        # ------------------------------------------------------
        changes, change_errors = self._parse_spending_changes(
            decision.get("spending_changes_needed")
        )
        errors.extend(change_errors)

        if not change_errors and events is not None:
            errors.extend(
                self._check_spending_changes_against_events(
                    changes, events
                )
            )

        # ------------------------------------------------------
        # 12. Explanation non-empty
        # ------------------------------------------------------
        explanation = decision.get("decision_explanation")
        if not explanation or not str(explanation).strip():
            errors.append("decision_explanation_empty")

        # ------------------------------------------------------
        # 13. Plan must complete by desired date
        # ------------------------------------------------------
        if plan and status in (
            "affordable_now",
            "affordable_with_plan",
        ):
            last_payment_date = plan[-1][0]
            if last_payment_date > desired_date:
                errors.append("plan_completes_after_desired_date")

        return {
            "valid": not errors,
            "errors": errors,
            "decision": decision,
        }

    # ==========================================================
    # PLAN PARSING
    # ==========================================================

    @staticmethod
    def _parse_plan(
        raw,
    ) -> tuple[list[tuple[date, float]], list[str]]:
        """
        Returns ([(date, amount), ...], errors) sorted chronologically.
        Accepts the literal string "none" (case-insensitive) for empty plans.
        """
        errors: list[str] = []

        if raw is None:
            errors.append("payment_plan_missing")
            return [], errors

        if isinstance(raw, str) and raw.strip().lower() in ("", "none"):
            return [], []

        if not isinstance(raw, str):
            errors.append(f"payment_plan_not_string:{type(raw).__name__}")
            return [], errors

        parts = [p for p in raw.split("|") if p.strip()]
        if not parts:
            return [], []

        parsed: list[tuple[date, float]] = []

        for item in parts:
            if ":" not in item:
                errors.append(f"plan_item_bad_format:{item}")
                continue

            date_str, amount_str = item.split(":", 1)
            try:
                d = date.fromisoformat(date_str.strip())
            except ValueError:
                errors.append(f"plan_item_bad_date:{item}")
                continue

            try:
                amt = float(amount_str.strip())
            except ValueError:
                errors.append(f"plan_item_bad_amount:{item}")
                continue

            if amt <= 0:
                errors.append(f"plan_item_nonpositive:{item}")
                continue

            parsed.append((d, amt))

        # Chronological order required.
        if parsed != sorted(parsed, key=lambda p: p[0]):
            errors.append("plan_not_chronological")
            parsed = sorted(parsed, key=lambda p: p[0])

        return parsed, errors

    # ==========================================================
    # PLAN SHAPE
    # ==========================================================

    @staticmethod
    def _check_plan_shape(
        plan,
        method,
        status,
        request_date: date,
        requested_amount: float,
        amount_safe_to_pay: float | None,
        earliest_parsed: date | None,
        payment_options: list[dict],
    ) -> list[str]:
        errors: list[str] = []

        if method == "not_recommended":
            if plan:
                errors.append("not_recommended_requires_empty_plan")
            return errors

        if method == "wait":
            if plan:
                errors.append("wait_requires_empty_plan")
            return errors

        # ------------------------------------------------------
        # full_payment
        # ------------------------------------------------------
        if method == "full_payment":
            if len(plan) != 1:
                errors.append("full_payment_requires_one_payment")
                return errors

            d, amt = plan[0]
            if d != request_date:
                errors.append("full_payment_must_be_on_request_date")
            if abs(amt - requested_amount) > 1e-6:
                errors.append("full_payment_amount_must_equal_requested")
            return errors

        # ------------------------------------------------------
        # partial_payment — exactly two payments
        # ------------------------------------------------------
        if method == "partial_payment":
            if len(plan) != 2:
                errors.append("partial_payment_requires_exactly_two_payments")
                return errors

            (d1, a1), (d2, a2) = plan

            if d1 != request_date:
                errors.append("partial_payment_first_must_be_today")

            if amount_safe_to_pay is None:
                errors.append("partial_payment_missing_amount_safe_to_pay")
            elif abs(a1 - amount_safe_to_pay) > 1e-6:
                errors.append(
                    "partial_payment_first_must_equal_amount_safe_to_pay"
                )

            if earliest_parsed is None:
                errors.append(
                    "partial_payment_requires_earliest_date"
                )
            elif d2 != earliest_parsed:
                errors.append(
                    "partial_payment_second_must_be_on_earliest_date"
                )

            if abs((a1 + a2) - requested_amount) > 1e-6:
                errors.append(
                    "partial_payment_total_must_equal_requested"
                )

            return errors

        # ------------------------------------------------------
        # installments — must match a supplied option exactly
        # ------------------------------------------------------
        if method == "installments":
            if not plan:
                errors.append("installments_requires_plan")
                return errors

            total = sum(a for _, a in plan)
            if abs(total - requested_amount) > 1e-6:
                errors.append("installments_total_must_equal_requested")

            if payment_options:
                if not DecisionValidator._plan_matches_any_option(
                    plan, payment_options
                ):
                    errors.append(
                        "installments_plan_does_not_match_supplied_option"
                    )

            return errors

        return errors

    # ==========================================================
    # INSTALLMENT OPTION MATCHING
    # ==========================================================

    @staticmethod
    def _plan_matches_any_option(
        plan: list[tuple[date, float]],
        payment_options: list[dict],
    ) -> bool:
        """
        Loose match: same number of payments, same total, and each
        payment date falls inside the option's [start, start+term]
        window. Tight enough to catch fabricated schedules without
        forcing byte-exact reconstruction of the option generator.
        """
        plan_dates = [d for d, _ in plan]
        plan_total = sum(a for _, a in plan)

        for opt in payment_options:
            try:
                start = date.fromisoformat(opt["payments_start_date"])
                interval = int(opt.get("days_between_payments") or 0)
                n = int(opt.get("number_of_payments") or len(plan))
                total = float(opt["total_payable_amount"])
            except (KeyError, TypeError, ValueError):
                continue

            if abs(plan_total - total) > 1e-4:
                continue

            if n != len(plan):
                continue

            # Each plan date must be >= the option's start date.
            if any(d < start for d in plan_dates):
                continue

            return True

        return False

    # ==========================================================
    # SPENDING CHANGES
    # ==========================================================

    @staticmethod
    def _parse_spending_changes(
        raw,
    ) -> tuple[list[dict], list[str]]:
        errors: list[str] = []

        if raw is None:
            errors.append("spending_changes_missing")
            return [], errors

        if isinstance(raw, str) and raw.strip().lower() in ("", "none"):
            return [], []

        if not isinstance(raw, str):
            errors.append(
                f"spending_changes_not_string:{type(raw).__name__}"
            )
            return [], errors

        parts = [p for p in raw.split("|") if p.strip()]
        if len(parts) > 3:
            errors.append("spending_changes_too_many")

        changes: list[dict] = []

        for item in parts:
            tokens = item.split(":")
            kind = tokens[0].strip().lower()

            if kind == "stop" and len(tokens) == 2:
                changes.append({"action": "stop", "event_id": tokens[1]})
            elif kind == "reduce_to" and len(tokens) == 3:
                try:
                    new_amount = float(tokens[2])
                except ValueError:
                    errors.append(f"spending_change_bad_amount:{item}")
                    continue
                if new_amount < 0:
                    errors.append(f"spending_change_negative_amount:{item}")
                    continue
                changes.append(
                    {
                        "action": "reduce_to",
                        "event_id": tokens[1],
                        "new_amount": new_amount,
                    }
                )
            else:
                errors.append(f"spending_change_bad_format:{item}")

        # Mutual exclusion: same event cannot be both stopped and reduced.
        stopped = {c["event_id"] for c in changes if c["action"] == "stop"}
        reduced = {c["event_id"] for c in changes if c["action"] == "reduce_to"}
        overlap = stopped & reduced
        if overlap:
            errors.append(
                f"spending_change_stop_and_reduce_conflict:{sorted(overlap)}"
            )

        return changes, errors

    @staticmethod
    def _check_spending_changes_against_events(
        changes: list[dict],
        events: list[dict],
    ) -> list[str]:
        errors: list[str] = []

        if not changes:
            return errors

        by_id = {e.get("event_id"): e for e in events if e.get("event_id")}

        for change in changes:
            event_id = change["event_id"]
            event = by_id.get(event_id)

            if event is None:
                errors.append(f"spending_change_unknown_event:{event_id}")
                continue

            flexibility = str(
                event.get("flexibility") or ""
            ).strip().lower()

            if flexibility != "flexible":
                errors.append(
                    f"spending_change_not_flexible:{event_id}"
                )

        return errors

    # ==========================================================
    # HELPERS
    # ==========================================================

    @staticmethod
    def _as_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ("true", "1", "yes", "y")