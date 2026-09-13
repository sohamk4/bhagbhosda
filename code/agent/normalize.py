# agent/normalize.py
"""
Fix spec violations in an LLM-produced decision row.

The tool-based flow lets the LLM emit the final numbers. That's fine for
most fields, but a few rules are non-negotiable and the model gets them
wrong often enough to matter.

This function does not re-decide. It only forces the output into a
spec-legal shape when the LLM's own answer is close but malformed.
"""

from __future__ import annotations


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


def normalize_decision(
    decision: dict,
    request: dict,
) -> tuple[dict, list[str]]:
    """
    Returns (fixed_decision, list_of_fixes_applied).
    """
    fixes: list[str] = []
    d = dict(decision)

    request_date = str(request["request_date"])
    requested_amount = float(request["requested_amount"])

    # ------------------------------------------------------
    # 1. amount_safe_to_pay must be a number, 0 <= x <= requested
    # ------------------------------------------------------
    raw = d.get("amount_safe_to_pay")
    try:
        amt = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        amt = 0.0
        fixes.append("amount_safe_to_pay_not_numeric")

    if amt < 0:
        amt = 0.0
        fixes.append("amount_safe_to_pay_clamped_to_zero")
    if amt > requested_amount:
        amt = requested_amount
        fixes.append("amount_safe_to_pay_clamped_to_requested")

    d["amount_safe_to_pay"] = amt

    # ------------------------------------------------------
    # 2. Enum fields
    # ------------------------------------------------------
    status = str(d.get("affordability_status") or "").strip()
    if status not in VALID_STATUSES:
        status = "not_affordable"
        fixes.append("invalid_status_coerced")

    method = str(d.get("recommended_payment_method") or "").strip()
    if method not in VALID_METHODS:
        method = "not_recommended"
        fixes.append("invalid_method_coerced")

    d["affordability_status"] = status
    d["recommended_payment_method"] = method

    # ------------------------------------------------------
    # 3. earliest_date_for_full_payment
    # ------------------------------------------------------
    earliest = d.get("earliest_date_for_full_payment")
    earliest_s = str(earliest).strip() if earliest is not None else ""

    if earliest_s.lower() == "none":
        earliest_s = ""

    if status == "affordable_now":
        if earliest_s != request_date:
            earliest_s = request_date
            fixes.append("earliest_date_forced_to_request_date")
        # Amount must equal requested for affordable_now.
        if abs(amt - requested_amount) > 1e-6:
            d["amount_safe_to_pay"] = requested_amount
            amt = requested_amount
            fixes.append("amount_forced_to_requested_for_affordable_now")

    d["earliest_date_for_full_payment"] = earliest_s

    # ------------------------------------------------------
    # 4. payment_plan — the big one
    # ------------------------------------------------------
    plan_raw = d.get("payment_plan")
    plan_s = str(plan_raw).strip() if plan_raw is not None else ""

    if status == "affordable_now" and method == "full_payment":
        # Spec: MUST be "<request_date>:<requested_amount>"
        expected = f"{request_date}:{_fmt_num(requested_amount)}"
        if plan_s.lower() in ("", "none") or ":" not in plan_s:
            plan_s = expected
            fixes.append("payment_plan_synthesized_for_affordable_now")
        else:
            # Even if LLM gave a plan, force the canonical form.
            if plan_s != expected:
                plan_s = expected
                fixes.append("payment_plan_forced_to_canonical")

    elif status in ("affordable_later", "not_affordable"):
        if method in ("wait", "not_recommended"):
            if plan_s and plan_s.lower() != "none":
                plan_s = "none"
                fixes.append("plan_cleared_for_wait_or_not_recommended")

    d["payment_plan"] = plan_s or "none"

    # ------------------------------------------------------
    # 5. spending_changes_needed
    # ------------------------------------------------------
    sc = d.get("spending_changes_needed")
    sc_s = str(sc).strip() if sc is not None else ""
    d["spending_changes_needed"] = sc_s or "none"

    # ------------------------------------------------------
    # 6. decision_explanation non-empty
    # ------------------------------------------------------
    exp = d.get("decision_explanation")
    exp_s = str(exp).strip() if exp is not None else ""
    if not exp_s:
        exp_s = _fallback_explanation(status, method, request, d)
        fixes.append("explanation_filled_from_template")
    d["decision_explanation"] = exp_s

    return d, fixes


# =============================================================
# Helpers
# =============================================================

def _fmt_num(value) -> str:
    v = float(value)
    if v.is_integer():
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _fallback_explanation(status, method, request, d) -> str:
    amount = request.get("requested_amount")
    if status == "affordable_now":
        return f"Full payment of {amount} is safe on the request date."
    if status == "affordable_with_plan":
        return f"Safe to proceed via {method.replace('_', ' ')}."
    if status == "affordable_later":
        return f"Full payment becomes safe on " \
               f"{d.get('earliest_date_for_full_payment', '')}."
    return "Request is not affordable within the 90-day forecast."