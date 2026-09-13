# main.py
"""
Run the deterministic decision pipeline for a single request.

Usage:
    python main.py request_19                 # deterministic, template explanation
    python main.py request_19 --llm           # same but with LLM explanation
    python main.py                            # defaults to request_26
"""
import json
import sys

from config import DATABASE_PATH
from database import create_connection
from engine.affordability import AffordabilityEngine
from engine.decision import DecisionBuilder
from engine.payment_plans import PaymentPlanEngine
from engine.validator import DecisionValidator
from services.container import ServiceContainer


def build_decision(services, request, validator):
    """Same pipeline that evaluation/main.py uses. Deterministic."""
    rid = request["request_id"]
    uid = request["user_id"]

    aff = AffordabilityEngine(services).evaluate(uid, rid)
    plans = PaymentPlanEngine(services).evaluate(uid, rid)

    decision = DecisionBuilder(services).build(
        request=request,
        affordability=aff,
        plan_result=plans,
    )

    result = validator.validate(
        decision,
        request,
        payment_options=services.payment_options.get_payment_options(rid),
        events=services.events.get_events(user_id=uid),
    )

    if not result["valid"]:
        decision = DecisionBuilder(services).safe_fallback(
            request, reason=result["errors"]
        )
        result = {"valid": True, "errors": [], "original_errors": result["errors"]}

    return decision, result


def explain_with_llm(request, decision):
    """
    One-shot explanation via LLM. No dependency on agent/nodes.py.
    Only overwrites decision_explanation; cannot change any numeric field.
    """
    try:
        from llm import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as exc:
        return decision, f"import failed: {exc}"

    try:
        llm = create_llm()
    except Exception as exc:
        return decision, f"LLM init failed: {exc}"

    summary = (
        f"Request: {request.get('request_text', '')}\n"
        f"Amount: {request.get('requested_amount')} "
        f"{request.get('home_currency', '')}\n"
        f"Deadline: {request.get('desired_completion_date')}\n"
        f"\nFINAL DECISION (do NOT change any number):\n"
        f"  amount_safe_to_pay: {decision.get('amount_safe_to_pay')}\n"
        f"  affordability_status: {decision.get('affordability_status')}\n"
        f"  recommended_payment_method: "
        f"{decision.get('recommended_payment_method')}\n"
        f"  payment_plan: {decision.get('payment_plan')}\n"
        f"  earliest_date_for_full_payment: "
        f"{decision.get('earliest_date_for_full_payment')}\n"
        f"  spending_changes_needed: "
        f"{decision.get('spending_changes_needed')}\n"
    )

    system_prompt = (
        "You write ONE short sentence (max 30 words) explaining a "
        "financial decision that has already been finalized. "
        "Do not change any number. Do not suggest alternatives. "
        "Do not mention the engine or the system. "
        "Return only the sentence. No markdown, no quotes, no JSON."
    )

    try:
        resp = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=summary),
        ])
        text = resp.content
        if isinstance(text, list):
            text = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in text
            )
        text = str(text).strip().strip('"').strip("'").strip()

        # Drop chain-of-thought leaks.
        for marker in (
            "here's a thinking process",
            "here is a thinking process",
            "let me think",
            "reasoning:",
            "analysis:",
        ):
            idx = text.lower().rfind(marker)
            if idx >= 0:
                text = text[idx + len(marker):].lstrip(" :\n\t")

        # Take last non-empty line.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            text = lines[-1]

        # Trim leading list markers.
        while text[:2] in ("1.", "2.", "3.", "- ", "* "):
            text = text[2:].strip()

        if len(text) > 240:
            text = text[:237].rstrip() + "..."

        if text and len(text) >= 10:
            decision = {**decision, "decision_explanation": text}
            return decision, None
        return decision, "LLM returned empty/short text"
    except Exception as exc:
        return decision, f"LLM call failed: {exc}"

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    request_id = args[0] if args else "request_26"
    use_llm = "--llm" in flags

    conn = create_connection(DATABASE_PATH)
    services = ServiceContainer(conn)
    validator = DecisionValidator()

    request = services.requests.get_request(request_id)
    if request is None:
        print(f"[error] request not found: {request_id}")
        return 1

    print(f"Running pipeline for {request_id} "
          f"(user {request['user_id']})...\n")

    decision, validation = build_decision(services, request, validator)

    if use_llm:
        print("[llm] generating explanation...")
        decision, err = explain_with_llm(request, decision)
        if err:
            print(f"[llm] {err}\n")

    print("========== DECISION ==========")
    print(json.dumps(decision, indent=2, default=str))
    print()
    print(f"validation: {validation['valid']}")
    if not validation["valid"]:
        for e in validation["errors"]:
            print(f"  - {e}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())