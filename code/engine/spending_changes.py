from __future__ import annotations

from datetime import date, timedelta


class SpendingChangeEngine:

    def __init__(self, services):
        self.services = services

    def find_best_changes(
        self,
        user_id: str,
        request_id: str,
        required_amount: float,
    ) -> dict:

        request = self.services.requests.get_request(
            request_id
        )

        if request is None:
            raise ValueError(
                f"Request not found: {request_id}"
            )

        profile = self.services.profile.get_profile(
            user_id
        )

        if profile is None:
            raise ValueError(
                f"Profile not found: {user_id}"
            )

        forecast = self._forecast(
            user_id,
            request_id,
        )

        candidates = self._get_candidates(
            user_id,
            request,
            profile,
        )

        if not candidates:
            return {
                "safe": False,
                "changes": [],
                "spending_changes_needed": "none",
            }

        # First try individual changes.
        for candidate in candidates:

            changes = [candidate]

            if self._safe_with_changes(
                profile,
                forecast,
                required_amount,
                changes,
            ):
                return self._result(
                    changes
                )

        # Then try pairs.
        for i in range(
            len(candidates)
        ):

            for j in range(
                i + 1,
                len(candidates),
            ):

                changes = [
                    candidates[i],
                    candidates[j],
                ]

                if self._safe_with_changes(
                    profile,
                    forecast,
                    required_amount,
                    changes,
                ):
                    return self._result(
                        changes
                    )

        # Then triples.
        for i in range(
            len(candidates)
        ):

            for j in range(
                i + 1,
                len(candidates)
            ):

                for k in range(
                    j + 1,
                    len(candidates)
                ):

                    changes = [
                        candidates[i],
                        candidates[j],
                        candidates[k],
                    ]

                    if self._safe_with_changes(
                        profile,
                        forecast,
                        required_amount,
                        changes,
                    ):
                        return self._result(
                            changes
                        )

        return {
            "safe": False,
            "changes": [],
            "spending_changes_needed": "none",
        }

    # ======================================================
    # CANDIDATES
    # ======================================================

    def _get_candidates(
        self,
        user_id,
        request,
        profile,
    ):

        events = self.services.events.get_events(
            user_id=user_id,
            start_date=request["request_date"],
            end_date=None,
        )

        candidates = []

        reducible = set(
            profile[
                "reducible_categories"
            ]
        )

        stoppable = set(
            profile[
                "stoppable_categories"
            ]
        )

        protected = set(
            profile[
                "protected_categories"
            ]
        )

        for event in events:

            if event["direction"] != "debit":
                continue

            if event["status"] not in {
                "settled",
                "scheduled",
                "pending",
            }:
                continue

            category = event["category"]

            if category in protected:
                continue

            amount = event["amount"]

            if amount is None:
                continue

            # Stoppable has priority.
            if (
                category in stoppable
                and event["flexibility"]
                in {
                    "stoppable",
                    "reducible_or_stoppable",
                }
            ):

                candidates.append(
                    {
                        "event_id":
                            event["event_id"],

                        "action":
                            "stop",

                        "category":
                            category,

                        "original_amount":
                            float(amount),

                        "new_amount":
                            0.0,
                    }
                )

                continue

            if (
                category in reducible
                and event["flexibility"]
                in {
                    "reducible",
                    "reducible_or_stoppable",
                }
            ):

                minimum = event[
                    "minimum_allowed_amount"
                ]

                if minimum is None:
                    minimum = 0.0

                minimum = float(
                    minimum
                )

                original = float(
                    amount
                )

                if minimum < original:

                    candidates.append(
                        {
                            "event_id":
                                event["event_id"],

                            "action":
                                "reduce",

                            "category":
                                category,

                            "original_amount":
                                original,

                            "new_amount":
                                minimum,
                        }
                    )

        return candidates

    # ======================================================
    # SIMULATION
    # ======================================================

    def _safe_with_changes(
        self,
        profile,
        forecast,
        required_amount,
        changes,
    ):

        balance = float(
            profile[
                "current_available_balance"
            ]
        )

        minimum = float(
            profile[
                "minimum_balance_to_keep"
            ]
        )

        change_map = {
            change["event_id"]: change
            for change in changes
        }

        events = forecast[
            "projected_events"
        ]

        start = date.fromisoformat(
            forecast["forecast_start"]
        )

        end = date.fromisoformat(
            forecast["forecast_end"]
        )

        payment_date = start

        current = start

        while current <= end:

            day = current.isoformat()

            for event in events:

                if event["event_date"] != day:
                    continue

                event_amount = float(
                    event["amount"]
                )

                if event["event_id"] in change_map:

                    change = change_map[
                        event["event_id"]
                    ]

                    event_amount = (
                        change["new_amount"]
                    )

                if event["direction"] == "credit":
                    balance += event_amount

                elif event["direction"] == "debit":
                    balance -= event_amount

            if day == payment_date.isoformat():
                balance -= required_amount

            if balance < minimum:
                return False

            current += timedelta(days=1)

        return True

    # ======================================================
    # RESULT
    # ======================================================

    @staticmethod
    def _result(
        changes,
    ):

        parts = []

        for change in changes:

            if change["action"] == "stop":

                parts.append(
                    f"stop:{change['event_id']}"
                )

            elif change["action"] == "reduce":

                amount = change[
                    "new_amount"
                ]

                if float(amount).is_integer():
                    amount_text = str(
                        int(amount)
                    )
                else:
                    amount_text = (
                        f"{amount:.2f}"
                        .rstrip("0")
                        .rstrip(".")
                    )

                parts.append(
                    "reduce_to:"
                    f"{change['event_id']}:"
                    f"{amount_text}"
                )

        return {
            "safe": True,
            "changes": changes,
            "spending_changes_needed":
                "|".join(parts),
        }

    # ======================================================
    # FORECAST
    # ======================================================

    def _forecast(
        self,
        user_id,
        request_id,
    ):

        from .forecast import ForecastEngine

        return ForecastEngine(
            self.services
        ).forecast(
            user_id,
            request_id,
        )