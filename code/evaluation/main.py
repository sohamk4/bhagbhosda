import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import create_connection
from config import DATABASE_PATH
from engine.affordability import AffordabilityEngine
from engine.decision import DecisionBuilder
from engine.payment_plans import PaymentPlanEngine
from engine.validator import DecisionValidator
from services.container import ServiceContainer
from engine.spending_changes import SpendingChangeEngine



OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

DATASET_DIR = ROOT.parent / "dataset"
OUTPUT_PATH = DATASET_DIR / "output.csv"


# =============================================================
# READ REQUEST IDS FROM EXISTING output.csv
# =============================================================

def read_request_ids_from_template(path: Path, limit=None) -> list[str]:
    """
    Read the request_id column from the existing output.csv.
    These are the rows we must produce predictions for.
    """
    if not path.exists():
        raise SystemExit(f"template not found: {path}")

    ids = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "request_id" not in (reader.fieldnames or []):
            raise SystemExit(
                f"output.csv has no 'request_id' column. "
                f"columns: {reader.fieldnames}"
            )
        for row in reader:
            rid = (row.get("request_id") or "").strip()
            if rid:
                ids.append(rid)

    if limit is not None:
        ids = ids[:limit]
    return ids


# =============================================================
# PIPELINE
# =============================================================

def build_decision(services, request, validator):
    rid = request["request_id"]
    uid = request["user_id"]

    aff = AffordabilityEngine(services).evaluate(uid, rid)
    plans = PaymentPlanEngine(services).evaluate(uid, rid)

    decision = DecisionBuilder(services).build(
        request=request,
        affordability=aff,
        plan_result=plans,
        spending_changes_needed="none",
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

    return decision

def normalize_amount(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else round(f, 2)


def write_csv(rows, out_path: Path):
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in OUTPUT_COLUMNS})


# =============================================================
# MAIN
# =============================================================

def main():
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            raise SystemExit("usage: python evaluation/main.py [limit]")

    request_ids = read_request_ids_from_template(OUTPUT_PATH, limit=limit)
    total = len(request_ids)

    print(f"Read {total} request_ids from {OUTPUT_PATH.name}"
          + (f" (limit={limit})" if limit else ""), flush=True)
    print("Running pipeline...\n", flush=True)

    conn = create_connection(DATABASE_PATH)
    services = ServiceContainer(conn)
    validator = DecisionValidator()

    rows = []
    failures = []
    started = time.time()

    for i, rid in enumerate(request_ids, 1):
        print(f"  [{i}/{total}] {rid} ...", end=" ", flush=True)

        try:
            request = services.requests.get_request(rid)
            if request is None:
                failures.append((rid, "not_found"))
                print("SKIP (not found)")
                continue

            decision = build_decision(services, request, validator)

            rows.append({
                "request_id": decision.get("request_id", rid),
                "amount_safe_to_pay": normalize_amount(
                    decision.get("amount_safe_to_pay", 0)
                ),
                "affordability_status": decision.get(
                    "affordability_status", "not_affordable"
                ),
                "recommended_payment_method": decision.get(
                    "recommended_payment_method", "not_recommended"
                ),
                "payment_plan": decision.get("payment_plan", "none"),
                "earliest_date_for_full_payment": decision.get(
                    "earliest_date_for_full_payment", ""
                ),
                "spending_changes_needed": decision.get(
                    "spending_changes_needed", "none"
                ),
                "decision_explanation": decision.get(
                    "decision_explanation", ""
                ),
            })
            print("OK", flush=True)

        except Exception as exc:
            failures.append((rid, str(exc)))
            print(f"ERROR: {exc}", flush=True)

        if i % 25 == 0:
            elapsed = time.time() - started
            print(f"       ... {elapsed:.1f}s elapsed "
                  f"({elapsed/i:.2f}s/row)", flush=True)

    write_csv(rows, OUTPUT_PATH)

    elapsed = time.time() - started
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  requests        : {total}")
    print(f"  rows written    : {len(rows)}")
    print(f"  failures        : {len(failures)}")
    print(f"  elapsed         : {elapsed:.1f}s "
          f"({elapsed/max(1,total):.2f}s/req)")
    print(f"  output          : {OUTPUT_PATH}")

    if failures:
        print()
        print("Failures:")
        for rid, err in failures[:20]:
            print(f"  {rid}: {err}")

    if rows:
        statuses, methods = {}, {}
        for r in rows:
            statuses[r["affordability_status"]] = statuses.get(
                r["affordability_status"], 0) + 1
            methods[r["recommended_payment_method"]] = methods.get(
                r["recommended_payment_method"], 0) + 1

        print()
        print("Status distribution:")
        for k, v in sorted(statuses.items(), key=lambda x: -x[1]):
            print(f"  {k:<24} {v}")
        print("Method distribution:")
        for k, v in sorted(methods.items(), key=lambda x: -x[1]):
            print(f"  {k:<24} {v}")

    conn.close()


if __name__ == "__main__":
    main()