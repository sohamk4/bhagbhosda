from typing import Any


class EventEnrichmentService:
    def __init__(self, services):
        self.services = services

    def enrich_events(
        self,
        events: list[dict],
    ) -> tuple[list[dict], list[dict]]:

        enriched_events = []
        image_context = []

        for event in events:
            event_copy = dict(event)

            # Nothing to enrich
            if event_copy.get("amount") is not None:
                enriched_events.append(event_copy)
                continue

            event_id = event_copy["event_id"]

            images = self.services.images.get_images(
                user_id=event_copy["user_id"],
                related_event_id=event_id,
            )

            if not images:
                enriched_events.append(event_copy)
                continue

            for image in images:
                image_path = self.services.images.get_image_path(
                    image["image_id"]
                )

                if not image_path:
                    continue

                try:
                    result = self.services.vision.extract_financial_facts(
                        image_path=image_path,
                        image_id=image["image_id"],
                        related_event_id=event_id,
                    )
                except Exception as exc:
                    # Vision failure must NOT break the financial forecast.
                    image_context.append(
                        {
                            "image_id": image["image_id"],
                            "related_event_id": event_id,
                            "image_path": image_path,
                            "error": str(exc),
                        }
                    )
                    continue

                image_context.append(result)

                facts = result.get("facts") or {}

                amount = facts.get('amount')
                confidence = facts.get('confidence', 0)
                currency = facts.get('currency')
                try:
                    confidence = float(confidence or 0)
                except (TypeError, ValueError):
                    confidence = 0

                if (
                    amount is not None
                    and confidence >= 0.05
                ):
                    try:
                        amount = float(amount)
                    except (TypeError, ValueError):
                        continue

                    event_copy["amount"] = amount
                    event_copy["amount_source"] = "image"
                    event_copy["was_enriched"] = True
                    event_copy["source_image_id"] = image["image_id"]
                    event_copy["image_confidence"] = confidence
                    event_copy["image_currency"] = currency
                    event_copy["image_evidence"] = facts.get("evidence")
                    event_copy["image_amount_label"] = facts.get(
                        "amount_label"
                    )

                    break

            enriched_events.append(event_copy)

        return enriched_events, image_context