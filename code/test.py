# check_spending.py
from config import DATABASE_PATH
from database import create_connection
from services.container import ServiceContainer
from engine.spending_changes import SpendingChangeEngine


conn = create_connection(DATABASE_PATH)
services = ServiceContainer(conn)

for rid in ["request_06", "request_11", "request_20", "request_05"]:
    req = services.requests.get_request(rid)
    if not req:
        print(f"{rid}: not found")
        continue

    try:
        r = SpendingChangeEngine(services).find_best_changes(
            user_id=req["user_id"],
            request_id=rid,
            required_amount=float(req["requested_amount"]),
        )
        print(f"{rid}: safe={r['safe']}  changes={r['spending_changes_needed']}")
    except Exception as exc:
        print(f"{rid}: ERROR: {type(exc).__name__}: {exc}")

conn.close()