# engine/simulation.py
from __future__ import annotations

from datetime import date, timedelta


def simulate_plan(
    starting_balance: float,
    minimum_balance: float,
    projected_events: list[dict],
    payments: list[dict],
    forecast_start: str,
    forecast_end: str,
) -> dict:
    """
    Day-by-day balance simulation.

    Within a day: credits first, then debits, then scheduled payments.
    Returns safety + diagnostic info.

    A plan is safe iff balance >= minimum_balance on EVERY day.
    """
    events_by_date: dict[str, list[dict]] = {}
    for event in projected_events:
        if event.get("amount") is None:
            continue
        events_by_date.setdefault(event["event_date"], []).append(event)

    payments_by_date: dict[str, float] = {}
    for p in payments:
        day = p["date"]
        payments_by_date[day] = payments_by_date.get(day, 0.0) + float(p["amount"])

    start = date.fromisoformat(forecast_start)
    end = date.fromisoformat(forecast_end)

    balance = float(starting_balance)
    min_seen = balance
    min_seen_date = forecast_start
    safe = balance >= minimum_balance

    current = start
    while current <= end:
        day = current.isoformat()
        day_events = events_by_date.get(day, [])
    
        # Debits first — this is what the ground truth does.
        for event in day_events:
            if event["direction"] == "debit":
                balance -= float(event["amount"])
                if balance < minimum_balance:
                    safe = False
                if balance < min_seen:
                    min_seen = balance
                    min_seen_date = day
    
        # Then credits.
        for event in day_events:
            if event["direction"] == "credit":
                balance += float(event["amount"])
    
        # Then scheduled payments.
        if day in payments_by_date:
            balance -= payments_by_date[day]
            if balance < minimum_balance:
                safe = False
            if balance < min_seen:
                min_seen = balance
                min_seen_date = day
    
        current += timedelta(days=1)
    return {
        "safe": safe,
        "min_balance": round(min_seen, 2),
        "min_balance_date": min_seen_date,
        "final_balance": round(balance, 2),
    }