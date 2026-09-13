from __future__ import annotations


class DecisionBuilder:
    """
    Merges AffordabilityEngine + PaymentPlanEngine + user preferences
    into the final output row.

    Contract:
        build(request, affordability, plan_result) -> dict with exactly:
            amount_safe_to_pay
            affordability_status
            recommended_payment_method
            payment_plan
            earliest_date_for_full_payment
            spending_changes_needed
            decision_explanation  (placeholder, LLM overwrites)
    """

    def __init__(self, services):
        self.services = services

    def build(
        self,
        request: dict,
        affordability: dict,
        plan_result: dict,
        spending_changes_needed: str = "none",
    ) -> dict:
        profile = self.services.profile.get_profile(request["user_id"])
        accepted = set(
            profile.get("payment_methods_user_will_consider")
            or profile.get("accepted_payment_methods")
            or []
        )

        request_date = request["request_date"]
        requested_amount = float(request["requested_amount"])
        earliest = affordability["earliest_date_for_full_payment"] or ""
        safe_today = affordability["amount_safe_to_pay"]

        # ------------------------------------------------------
        # Case 1: full payment today is safe AND user accepts it.
        # ------------------------------------------------------
        if earliest == request_date and "full_payment" in accepted:
            return self._row(
                request,
                amount_safe_to_pay=round(requested_amount, 2),
                status="affordable_now",
                method="full_payment",
                plan=f"{request_date}:{self._fmt(requested_amount)}",
                earliest=request_date,
                spending_changes=spending_changes_needed,
            )

        # ------------------------------------------------------
        # Case 2: a plan (partial or installment) is viable.
        # ------------------------------------------------------
        viable = plan_result.get("viable_options") or []
        if viable:
            best = viable[0]
            return self._row(
                request,
                amount_safe_to_pay=safe_today,
                status="affordable_with_plan",
                method=best["recommended_payment_method"],
                plan=best["payment_plan"],
                earliest=earliest,
                spending_changes=spending_changes_needed,   
            )

        # ------------------------------------------------------
        # Case 3: full payment becomes safe later AND user accepts
        # full_payment (the "wait" path).
        # ------------------------------------------------------
        if earliest and "full_payment" in accepted:
            return self._row(
                request,
                amount_safe_to_pay=safe_today,
                status="affordable_later",
                method="wait",
                plan="none",
                earliest=earliest,
                spending_changes=spending_changes_needed,  
            )

        # ------------------------------------------------------
        # Case 4: nothing works.
        # ------------------------------------------------------
        return self._row(
            request,
            amount_safe_to_pay=safe_today,
            status="not_affordable",
            method="not_recommended",
            plan="none",
            earliest=earliest,
            spending_changes=spending_changes_needed,  
        )

    # ==========================================================
    # FALLBACK — used by validator escape hatch
    # ==========================================================

    def safe_fallback(self, request: dict, reason: list[str] | None = None) -> dict:
        request_date = request["request_date"]
        return self._row(
            request,
            amount_safe_to_pay=0.0,
            status="not_affordable",
            method="not_recommended",
            plan="none",
            earliest="",
        )

    # ==========================================================
    # INTERNAL
    # ==========================================================

    def _row(
        self,
        request: dict,
        amount_safe_to_pay: float,
        status: str,
        method: str,
        plan: str,
        earliest: str,
        spending_changes: str = "none", 
    ) -> dict:
        return {
            "request_id": request["request_id"],
            "amount_safe_to_pay": amount_safe_to_pay,
            "affordability_status": status,
            "recommended_payment_method": method,
            "payment_plan": plan or "none",
            "earliest_date_for_full_payment": earliest or "",
            "spending_changes_needed": spending_changes or "none",
            "spending_changes_needed": "none",
            "decision_explanation": self._template_explanation(
                request, status, method, earliest,
            ),
        }
    
    @staticmethod
    def _template_explanation(
        request: dict,
        status: str,
        method: str,
        earliest: str,
    ) -> str:
        raw = request.get("requested_amount")
        # Use the same formatter as payment plans.
        amount = DecisionBuilder._fmt(float(raw)) if raw is not None else "the amount"
    
        if status == "affordable_now":
            return f"Full payment of {amount} is safe on the request date."
        if status == "affordable_with_plan":
            return f"Safe to proceed via {method.replace('_', ' ')}."
        if status == "affordable_later":
            return f"Full payment becomes safe on {earliest}."
        return "Request is not affordable within the 90-day forecast."

    @staticmethod
    def _fmt(amount: float) -> str:
        amount = float(amount)
        if amount.is_integer():
            return str(int(amount))
        return f"{amount:.2f}".rstrip("0").rstrip(".")