from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median


class ForecastEngine:
    """
    Forecast future cash-flow events from historical and explicit events.

    Design:
    - Fixed commitments are allowed to form recurring schedules.
    - Variable spending is forecast conservatively.
    - Recurrence requires stronger evidence than two matching gaps.
    - Actual/explicit future events take precedence over synthetic events.
    - Non-cash, failed, cancelled, unrealized, and unknown-amount events
      do not affect the cash forecast.
    - Linked events are resolved before any aggregation: an explicit
      cancellation / settlement / amendment supersedes the earlier event.
    - All amounts are normalized to the user's home currency before
      deduplication and forecasting.
    - Spending changes are applied to the merged projected timeline.
    """

    # Expenses/income where recurrence is generally meaningful.
    FIXED_RECURRING_CATEGORIES = {
        "rent",
        "salary",
        "debt_repayment",
        "family_support",
        "cloud_storage",
        "utilities",
        "healthcare",
        "loan",
        "insurance",
        "subscription",
        "emi",
        "mortgage",
        "pension",
    }

    # These categories are naturally variable.
    VARIABLE_CATEGORIES = {
        "groceries",
        "transport",
        "shopping",
        "food",
        "dining",
        "entertainment",
        "fuel",
        "travel",
        "personal_care",
    }

    # Type-level markers for cancellation / amendment records.
    SUPERSEDING_EVENT_TYPES = {
        "cancellation",
        "cancel",
        "canceled",
        "cancelled",
        "settlement",
        "amendment",
        "amended",
        "adjustment",
        "refund",
    }

    def __init__(self, services):
        self.services = services

    # ==========================================================
    # MAIN FORECAST
    # ==========================================================

    def forecast(
        self,
        user_id: str,
        request_id: str,
        spending_changes: list[dict] | None = None,
        currency_converter=None,
    ) -> dict:
        """
        Parameters
        ----------
        spending_changes
            Optional list of dicts:
                {"action": "stop",      "event_id": "event_14"}
                {"action": "reduce_to", "event_id": "event_21",
                 "new_amount": 100}
            Applied to the merged projected timeline only — never to
            historical events.
        currency_converter
            Optional callable:
                (from_ccy, to_ccy, on_date_str, request_date_str) -> float | None
            Returns the rate to multiply `from_ccy` by to get `to_ccy`,
            or None if no rate is available. When None, events are treated
            as already in home currency.
        """
        request = self._get_request(request_id)
        profile = self.services.profile.get_profile(user_id)
    
        if profile is None:
            raise ValueError(f"Profile not found: {user_id}")
    
        home_ccy = str(profile["home_currency"]).strip().upper()
    
        request_date = date.fromisoformat(request["request_date"])
        forecast_end = request_date + timedelta(days=90)
    
        events = self.services.events.get_events(
            user_id=user_id,
            start_date=(request_date - timedelta(days=180)).isoformat(),
            end_date=forecast_end.isoformat(),
        )
    
        # ------------------------------------------------------
        # Enrichment: missing amounts, image extraction, etc.
        # ------------------------------------------------------
        events, image_context = self.services.event_enrichment.enrich_events(events)
    
        # FIX #6 — resolve linked events (cancellations / amendments)
        # before anything else touches the event stream.
        events = self._resolve_linked_events(events)
    
        # FIX #7 — normalize all amounts to home currency so dedup and
        # forecasting operate on the same units.
        events, conversion_failures = self._convert_events_to_home_currency(
            events,
            home_ccy=home_ccy,
            converter=currency_converter,
            request_date_str=request["request_date"],
        )
    
        events = self._deduplicate_events(events)
    
        # ======================================================
        # === FIX: adjust starting balance for enriched pre-request events ===
        #
        # Events whose amounts were resolved FROM IMAGES and are dated BEFORE
        # the request_date are not reflected in profile.current_available_balance
        # (the snapshot was taken when those amounts were still unknown).
        # Apply them to the starting balance so the trajectory includes them.
        # ======================================================
        pre_request_enriched = [
            e for e in events
            if e.get("was_enriched")
            and e.get("event_date") < request["request_date"]
            and e.get("status") == "settled"
            and e.get("direction") in ("credit", "debit")
            and e.get("amount") is not None
        ]
    
        adjusted_start = float(profile["current_available_balance"])
        for e in pre_request_enriched:
            if e["direction"] == "credit":
                adjusted_start += float(e["amount"])
            else:
                adjusted_start -= float(e["amount"])
    
        # ------------------------------------------------------
        # Historical events used for learning recurrence.
        # ------------------------------------------------------
        historical_events = [
            event
            for event in events
            if event["event_date"] < request["request_date"]
            and event.get("status") == "settled"
            and event.get("amount") is not None
            and event.get("direction") != "non_cash"
            and event.get("event_type") != "investment_valuation"
        ]
    
        # ------------------------------------------------------
        # Explicit future events.
        # ------------------------------------------------------
        future_events = [
            event
            for event in events
            if request["request_date"] <= event["event_date"] <= forecast_end.isoformat()
            and self._is_forecast_event(event)
        ]
    
        # ------------------------------------------------------
        # Infer recurring events.
        # ------------------------------------------------------
        recurring_events = self._infer_recurring_events(
            historical_events=historical_events,
            request_date=request_date,
            forecast_end=forecast_end,
        )
        # ADD THESE LINES:
        variable_aggregates = self._infer_variable_category_aggregates(
            historical_events=historical_events,
            request_date=request_date,
            forecast_end=forecast_end,
            home_ccy=home_ccy,
        )
        recurring_events = recurring_events + variable_aggregates
    
        # ------------------------------------------------------
        # Merge explicit + inferred events. Explicit always win.
        # ------------------------------------------------------
        projected_events = self._merge_events(
            explicit_events=future_events,
            recurring_events=recurring_events,
        )
    
        # FIX #5 — apply spending changes to the merged timeline.
        projected_events, applied_changes = self._apply_spending_changes(
            projected_events,
            spending_changes or [],
        )
    
        # ------------------------------------------------------
        # Calculate daily balances.
        # ------------------------------------------------------
        # === FIX: use adjusted_start, not the raw profile balance ===
        balance = adjusted_start
        minimum_balance = float(profile["minimum_balance_to_keep"])
    
        daily_balances = []
        by_date = defaultdict(list)
    
        for event in projected_events:
            by_date[event["event_date"]].append(event)
    
        current = request_date
        while current <= forecast_end:
            current_string = current.isoformat()
    
            for event in by_date.get(current_string, []):
                amount = event.get("amount")
                if amount is None:
                    continue
    
                if event["direction"] == "credit":
                    balance += float(amount)
                elif event["direction"] == "debit":
                    balance -= float(amount)
    
            daily_balances.append(
                {
                    "date": current_string,
                    "balance": round(balance, 2),
                    "safe": balance >= minimum_balance,
                }
            )
    
            current += timedelta(days=1)
    
        minimum_point = min(daily_balances, key=lambda item: item["balance"])
    
        return {
            "request_id": request_id,
            "user_id": user_id,
            "home_currency": home_ccy,
            "forecast_start": request["request_date"],
            "forecast_end": forecast_end.isoformat(),
            # === FIX: report adjusted_start, not the raw profile balance ===
            "starting_balance": round(adjusted_start, 2),
            "starting_balance_snapshot": round(
                float(profile["current_available_balance"]), 2
            ),
            "pre_request_enriched_events": pre_request_enriched,
            "adjusted_from_snapshot": round(
                adjusted_start - float(profile["current_available_balance"]), 2
            ),
            "minimum_balance_required": minimum_balance,
            "minimum_projected_balance": minimum_point["balance"],
            "minimum_balance_date": minimum_point["date"],
            "forecast_safe": all(item["safe"] for item in daily_balances),
            "historical_events": historical_events,
            "projected_events": projected_events,
            "image_context": image_context,
            "daily_balances": daily_balances,
            "applied_spending_changes": applied_changes,
            "conversion_failures": conversion_failures,
        }

    # ==========================================================
    # FIX #6 — LINKED EVENT RESOLUTION
    # ==========================================================

    def _resolve_linked_events(self, events: list[dict]) -> list[dict]:
        """
        Drop earlier events that a later record explicitly supersedes.

        Superseding conditions (per problem's conflict rules):
          1. Newer event from the same source (later event_date).
          2. Settled event replacing a pending/scheduled one.
          3. Explicit cancellation / settlement / amendment event_type.
        """
        by_id = {e["event_id"]: e for e in events if e.get("event_id")}
        superseded: set[str] = set()

        for event in events:
            link = event.get("linked_event_id")
            if not link:
                continue

            earlier = by_id.get(link)
            if earlier is None or earlier is event:
                continue

            newer = event.get("event_date", "") > earlier.get("event_date", "")
            settled_over_pending = (
                earlier.get("status") in ("pending", "scheduled")
                and event.get("status") == "settled"
            )
            explicit_cancel = (
                str(event.get("event_type") or "").strip().lower()
                in self.SUPERSEDING_EVENT_TYPES
            )

            if newer or settled_over_pending or explicit_cancel:
                superseded.add(link)

        return [e for e in events if e.get("event_id") not in superseded]

    # ==========================================================
    # FIX #7 — CURRENCY CONVERSION
    # ==========================================================

    def _convert_events_to_home_currency(
        self,
        events: list[dict],
        home_ccy: str,
        converter,
        request_date_str: str,
    ) -> tuple[list[dict], list[dict]]:
        """
        Normalize every event's amount into the user's home currency.

        Returns (converted_events, failures) where failures is a list of
        small dicts describing any events whose rate could not be found.
        Events without a rate are kept but with amount=None so downstream
        code skips them rather than treating them as zero.
        """
        if converter is None:
            return events, []

        dst = home_ccy.strip().upper()
        converted: list[dict] = []
        failures: list[dict] = []

        for event in events:
            amount = event.get("amount")
            if amount is None:
                converted.append(event)
                continue

            src = str(event.get("currency") or dst).strip().upper()

            if src == dst:
                converted.append({**event, "currency": dst})
                continue

            rate = converter(src, dst, event["event_date"], request_date_str)

            if rate is None:
                failures.append(
                    {
                        "event_id": event.get("event_id"),
                        "from": src,
                        "to": dst,
                        "on": event["event_date"],
                        "reason": "no_rate",
                    }
                )
                converted.append(
                    {
                        **event,
                        "amount": None,
                        "conversion_failed": True,
                    }
                )
                continue

            converted.append(
                {
                    **event,
                    "original_amount": amount,
                    "original_currency": src,
                    "amount": round(float(amount) * float(rate), 2),
                    "currency": dst,
                }
            )

        return converted, failures

    # ==========================================================
    # FIX #5 — SPENDING CHANGES
    # ==========================================================

    def _apply_spending_changes(
        self,
        events: list[dict],
        changes: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """
        Apply stop / reduce_to changes to the projected timeline.

        A change targeting a source event_id also affects any synthetic
        recurring event whose source_event_ids include that id — this is
        how "stop:event_14" cancels future recurrences of a pattern.

        Stop and reduce_to are mutually exclusive per event_id.
        """
        if not changes:
            return events, []

        stopped: set[str] = set()
        reduced: dict[str, float] = {}

        for change in changes:
            action = str(change.get("action") or "").lower()
            event_id = change.get("event_id")
            if not event_id:
                continue

            if action == "stop":
                stopped.add(event_id)
            elif action == "reduce_to":
                try:
                    reduced[event_id] = float(change["new_amount"])
                except (KeyError, TypeError, ValueError):
                    continue

        # Mutually exclusive: a stop supersedes a reduce on the same event.
        for eid in list(reduced.keys()):
            if eid in stopped:
                del reduced[eid]

        applied: list[dict] = []
        result: list[dict] = []

        for event in events:
            eid = event.get("event_id")
            source_ids = set(event.get("source_event_ids") or [])

            # Direct hit.
            if eid in stopped:
                applied.append({"action": "stop", "event_id": eid,
                                "applied_to": "explicit"})
                continue

            if eid in reduced:
                applied.append({"action": "reduce_to", "event_id": eid,
                                "new_amount": reduced[eid],
                                "applied_to": "explicit"})
                result.append(
                    {**event, "amount": reduced[eid],
                     "modified_by": "spending_change"}
                )
                continue

            # Synthetic hit via source pattern.
            if source_ids & stopped:
                hit = sorted(source_ids & stopped)[0]
                applied.append({"action": "stop", "event_id": hit,
                                "applied_to": "synthetic",
                                "forecast_event_id": eid})
                continue

            hit_ids = source_ids & reduced.keys()
            if hit_ids:
                # Most conservative reduction wins.
                new_amount = min(reduced[x] for x in hit_ids)
                hit = sorted(hit_ids)[0]
                applied.append({"action": "reduce_to", "event_id": hit,
                                "new_amount": new_amount,
                                "applied_to": "synthetic",
                                "forecast_event_id": eid})
                result.append(
                    {**event, "amount": new_amount,
                     "modified_by": "spending_change"}
                )
                continue

            result.append(event)

        return result, applied

    # ==========================================================
    # DEDUPLICATION
    # ==========================================================

    @staticmethod
    def _deduplicate_events(events: list[dict]) -> list[dict]:
        result = []
        seen = set()

        for event in events:
            key = (
                event.get("event_id"),
                event.get("event_date"),
                event.get("event_type"),
                event.get("category"),
                event.get("direction"),
                event.get("amount"),
                event.get("currency"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(event)

        return result

    # ==========================================================
    # REQUEST
    # ==========================================================

    def _get_request(self, request_id: str) -> dict:
        request = self.services.requests.get_request(request_id)
        if request is None:
            raise ValueError(f"Request not found: {request_id}")
        return request

    # ==========================================================
    # RECURRENCE INFERENCE
    # ==========================================================

    def _infer_recurring_events(
        self,
        historical_events: list[dict],
        request_date: date,
        forecast_end: date,
    ) -> list[dict]:
        # ==================================================
        # TERMINATION DETECTION — stream level
        #
        # Groups are split by description, so a stream like salary can
        # produce multiple groups ("Payroll credit" × 4, then
        # "Final employer payroll" × 1). Detect termination at the
        # (category, direction, currency) level by looking at the SINGLE
        # LATEST event across all descriptions for that stream.
        # ==================================================
        TERMINATION_MARKERS = (
            "final",
            "last",
            "terminated",
            "cancelled",
            "canceled",
            "closed",
            "ended",
            "resigned",
            "quit",
            "left employer",
            "no longer",
            "discontinued",
            "contract ended",
            "laid off",
            "redundancy",
            "severance",
            "last paycheck",
            "last salary",
            "final salary",
            "final pay",
            "final rent",
            "final bill",
            "final payment",
        )

        latest_by_stream: dict[tuple, dict] = {}
        for event in historical_events:
            if event.get("amount") is None:
                continue
            category = str(event.get("category") or "").strip().lower()
            direction = str(event.get("direction") or "").strip().lower()
            currency = event.get("currency")
            stream_key = (category, direction, currency)

            current = latest_by_stream.get(stream_key)
            if current is None or event["event_date"] > current["event_date"]:
                latest_by_stream[stream_key] = event

        terminated_streams: set[tuple] = set()
        for stream_key, latest in latest_by_stream.items():
            description = str(latest.get("description") or "").strip().lower()
            if any(marker in description for marker in TERMINATION_MARKERS):
                terminated_streams.add(stream_key)

        # ==================================================
        # GROUP BY (event_type, category, description, direction, currency)
        # ==================================================
        groups: dict[tuple, list[dict]] = defaultdict(list)

        for event in historical_events:
            if event.get("amount") is None:
                continue
            if event.get("status") != "settled":
                continue
            if event.get("event_type") == "investment_valuation":
                continue
            if event.get("direction") == "non_cash":
                continue

            category = str(event.get("category") or "").strip().lower()
            event_type = str(event.get("event_type") or "").strip().lower()

            if category in self.VARIABLE_CATEGORIES:
                continue
            if category not in self.FIXED_RECURRING_CATEGORIES:
                continue

            key = (
                event_type,
                category,
                event.get("description"),
                event.get("direction"),
                event.get("currency"),
            )
            groups[key].append(event)

        # ==================================================
        # EMIT FUTURE EVENTS PER GROUP
        # ==================================================
        recurring_events: list[dict] = []

        for key, group in groups.items():
            event_type, category, description, direction, currency = key

            # Stream-level termination — skip ALL groups for this stream.
            if (category, direction, currency) in terminated_streams:
                continue

            # Require at least 3 observations.
            if len(group) < 3:
                continue

            group = sorted(group, key=lambda e: e["event_date"])
            dates = [date.fromisoformat(e["event_date"]) for e in group]

            gaps = [
                (dates[i] - dates[i - 1]).days
                for i in range(1, len(dates))
            ]
            if not gaps:
                continue

            recurrence = self._detect_recurrence(gaps)
            if recurrence is None:
                continue

            frequency_name, typical_gap = recurrence

            # Prefer recent observations so schedule drift is respected.
            amounts = [
                float(e["amount"])
                for e in group
                if e.get("amount") is not None
            ]
            if not amounts:
                continue

            recent_amounts = amounts[-4:] if len(amounts) >= 4 else amounts
            typical_amount = float(median(recent_amounts))

            last_event = group[-1]
            last_date = dates[-1]

            next_date = self._next_recurring_date(
                last_date=last_date,
                typical_gap=typical_gap,
                frequency_name=frequency_name,
                request_date=request_date,
            )

            while next_date <= forecast_end:
                recurring_events.append(
                    {
                        "event_id": (
                            f"forecast:{key[0]}:{key[1]}:{next_date}"
                        ),
                        "event_type": key[0],
                        "description": key[2],
                        "category": key[1],
                        "direction": key[3],
                        "amount": typical_amount,
                        "currency": key[4],
                        "event_date": next_date.isoformat(),
                        "settlement_date": next_date.isoformat(),
                        "status": "forecasted",
                        "flexibility": last_event.get("flexibility"),
                        "minimum_allowed_amount": last_event.get(
                            "minimum_allowed_amount"
                        ),
                        "recurrence": frequency_name,
                        "source_event_ids": [e["event_id"] for e in group],
                    }
                )

                next_date = self._next_recurring_date(
                    last_date=next_date,
                    typical_gap=typical_gap,
                    frequency_name=frequency_name,
                    request_date=request_date,
                )

        return recurring_events
    def _infer_variable_category_aggregates(
        self,
        historical_events: list[dict],
        request_date: date,
        forecast_end: date,
        home_ccy: str,
    ) -> list[dict]:
        """
        Variable categories (groceries, transport, shopping, ...) are
        recurring in nature but irregular in timing. Emit a weekly
        synthetic debit per category using the historical daily average.
        """
        groups: dict[str, list[dict]] = defaultdict(list)
    
        for event in historical_events:
            if event.get("direction") != "debit":
                continue
            if event.get("amount") is None:
                continue
    
            category = str(event.get("category") or "").strip().lower()
            if category not in self.VARIABLE_CATEGORIES:
                continue
    
            groups[category].append(event)
    
        synthetic: list[dict] = []
    
        for category, group in groups.items():
            if len(group) < 3:
                continue
    
            dates = sorted(
                date.fromisoformat(e["event_date"]) for e in group
            )
            amounts = [float(e["amount"]) for e in group]
    
            span_days = (dates[-1] - dates[0]).days
            if span_days <= 0:
                continue
    
            daily_rate = sum(amounts) / span_days
            weekly_amount = round(daily_rate * 7 * 0.6, 2)   # dampen by 40%
    
            if weekly_amount <= 0:
                continue
    
            next_date = request_date + timedelta(days=3)
            while next_date <= forecast_end:
                synthetic.append({
                    "event_id": f"forecast_var:{category}:{next_date}",
                    "event_type": "expense",
                    "description": f"Forecast {category} (weekly avg)",
                    "category": category,
                    "direction": "debit",
                    "amount": weekly_amount,
                    "currency": home_ccy,
                    "event_date": next_date.isoformat(),
                    "settlement_date": next_date.isoformat(),
                    "status": "forecasted",
                    "recurrence": "weekly",
                    "source_event_ids": [e["event_id"] for e in group],
                })
                next_date += timedelta(days=7)
    
        return synthetic
        # ==========================================================
        # RECURRENCE DETECTION
        # ==========================================================
    
    @staticmethod
    def _detect_recurrence(gaps: list[int]) -> tuple[str, int] | None:
        if not gaps:
            return None

        patterns = {
            "weekly":    {"target": 7,  "tolerance": 1, "minimum_matches": 3},
            "biweekly":  {"target": 14, "tolerance": 2, "minimum_matches": 3},
            "monthly":   {"target": 30, "tolerance": 4, "minimum_matches": 3},
            "quarterly": {"target": 90, "tolerance": 5, "minimum_matches": 3},
        }

        candidates = []

        for name, config in patterns.items():
            target = config["target"]
            tolerance = config["tolerance"]
            minimum_matches = config["minimum_matches"]

            matching = [
                gap for gap in gaps
                if abs(gap - target) <= tolerance
            ]
            if len(matching) < minimum_matches:
                continue

            support_ratio = len(matching) / len(gaps)
            if support_ratio < 0.60:
                continue

            candidates.append(
                (
                    name,
                    int(round(median(matching))),
                    len(matching),
                    support_ratio,
                )
            )

        if not candidates:
            return None

        targets = {
            "weekly": 7,
            "biweekly": 14,
            "monthly": 30,
            "quarterly": 90,
        }

        candidates.sort(
            key=lambda item: (
                item[3],
                item[2],
                -abs(item[1] - targets[item[0]]),
            ),
            reverse=True,
        )

        name, gap, _, _ = candidates[0]
        return name, gap

    # ==========================================================
    # NEXT RECURRING DATE
    # ==========================================================

    @staticmethod
    def _next_recurring_date(
        last_date: date,
        typical_gap: int,
        frequency_name: str,
        request_date: date,
    ) -> date:
        """
        FIX #3 — dispatch table instead of a conditional ladder.
        Weekly/biweekly now use their nominal interval (7/14) instead
        of `typical_gap`, which may have drifted due to tolerance.
        """
        if frequency_name == "weekly":
            step = lambda d: d + timedelta(days=7)
        elif frequency_name == "biweekly":
            step = lambda d: d + timedelta(days=14)
        elif frequency_name == "monthly":
            step = lambda d: ForecastEngine._add_months(d, 1)
        elif frequency_name == "quarterly":
            step = lambda d: ForecastEngine._add_months(d, 3)
        else:
            step = lambda d: d + timedelta(days=typical_gap)

        candidate = step(last_date)
        while candidate < request_date:
            candidate = step(candidate)

        return candidate

    # ==========================================================
    # MONTH ARITHMETIC
    # ==========================================================

    @staticmethod
    def _add_months(current: date, months: int) -> date:
        total_months = current.year * 12 + (current.month - 1) + months
        year = total_months // 12
        month = total_months % 12 + 1
        day = min(current.day, ForecastEngine._days_in_month(year, month))
        return date(year, month, day)

    @staticmethod
    def _days_in_month(year: int, month: int) -> int:
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        return (next_month - timedelta(days=1)).day

    # ==========================================================
    # MERGE EVENTS
    # ==========================================================

    @staticmethod
    def _merge_events(
        explicit_events: list[dict],
        recurring_events: list[dict],
    ) -> list[dict]:
        result = list(explicit_events)

        # FIX #1 — dedup key no longer includes `description`.
        # A scheduled salary row and its synthetic recurrence almost
        # never share a description; including it caused double-counting.
        explicit_keys = {
            (
                event.get("event_date"),
                event.get("event_type"),
                event.get("category"),
                event.get("direction"),
            )
            for event in explicit_events
        }

        # Variable-category index for conservative suppression.
        explicit_by_category = defaultdict(list)
        for event in explicit_events:
            category = str(event.get("category") or "").strip().lower()
            if category in ForecastEngine.VARIABLE_CATEGORIES:
                explicit_by_category[category].append(
                    date.fromisoformat(event["event_date"])
                )

        for event in recurring_events:
            key = (
                event.get("event_date"),
                event.get("event_type"),
                event.get("category"),
                event.get("direction"),
            )
            if key in explicit_keys:
                continue

            category = str(event.get("category") or "").strip().lower()
            event_date = date.fromisoformat(event["event_date"])

            if category in ForecastEngine.VARIABLE_CATEGORIES:
                nearby_dates = explicit_by_category.get(category, [])
                has_nearby_actual = any(
                    abs((actual_date - event_date).days) <= 3
                    for actual_date in nearby_dates
                )
                if has_nearby_actual:
                    continue

            result.append(event)

        return sorted(
            result,
            key=lambda event: (event["event_date"], event["event_id"]),
        )

    # ==========================================================
    # FORECAST EVENT FILTER
    # ==========================================================

    @staticmethod
    def _is_forecast_event(event: dict) -> bool:
        status = str(event.get("status") or "").strip().lower()
        direction = str(event.get("direction") or "").strip().lower()
        event_type = str(event.get("event_type") or "").strip().lower()

        if status in ("failed", "cancelled", "canceled", "unrealized"):
            return False

        if direction == "non_cash":
            return False

        if event_type == "investment_valuation":
            return False

        # Pending credits cannot be assumed to be available.
        if status == "pending" and direction == "credit":
            return False

        # Unknown amount cannot safely be simulated.
        if event.get("amount") is None:
            return False

        return status in ("settled", "scheduled", "pending")