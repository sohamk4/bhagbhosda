from typing import Any

from langchain_core.tools import tool
from datetime import date, timedelta

class ContextTools:

    def __init__(self, services):
        self.services = services

    def get_tools(self) -> list:

        services = self.services

        @tool
        def get_financial_context(
            user_id: str,
            request_id: str,
        ) -> dict[str, Any]:
            """
            Retrieve compact financial context for a request.

            This does not return the user's entire financial history.

            If a financial event has a missing amount and a related image
            exists, the image is analyzed using the vision service and the
            extracted amount is merged into the runtime event context.
            """

            request = services.requests.get_request(
                request_id
            )

            if request is None:
                raise ValueError(
                    f"Request not found: {request_id}"
                )

            profile = services.profile.get_profile(
                user_id
            )
            print(profile)

            if profile is None:
                raise ValueError(
                    f"Profile not found: {user_id}"
                )

            request_date = request["request_date"]

            completion_date = request[
                "desired_completion_date"
            ]

            # ---------------------------------------------------------
            # 1. Retrieve financial events
            # ---------------------------------------------------------

            request_date_obj = date.fromisoformat(request_date)

            historical_start_date = (
                request_date_obj - timedelta(days=90)
            ).isoformat()
            
            events = services.events.get_events(
                user_id=user_id,
                start_date=historical_start_date,
                end_date=completion_date,
            )

            # ---------------------------------------------------------
            # 2. Enrich events with image-derived financial facts
            # ---------------------------------------------------------
            #
            # IMPORTANT:
            # This does NOT modify the database.
            #
            # If an event already has an amount, the DB value wins.
            #
            # If amount is NULL and a related image exists, VisionService
            # extracts the financial amount and we merge it into the
            # runtime event only.
            # ---------------------------------------------------------

            events, image_context = services.event_enrichment.enrich_events(
                events=events,
            )

            # ---------------------------------------------------------
            # 3. Retrieve messages
            # ---------------------------------------------------------

            messages = services.messages.get_messages(
                user_id=user_id,
                request_id=request_id,
            )

            # ---------------------------------------------------------
            # 4. Retrieve image metadata
            # ---------------------------------------------------------

            images = services.images.get_images(
                user_id=user_id,
                request_id=request_id,
            )

            # ---------------------------------------------------------
            # 5. Retrieve allowed payment options
            # ---------------------------------------------------------

            payment_options = (
                services.payment_options
                .get_payment_options(request_id)
            )

            # ---------------------------------------------------------
            # 6. Return compact context
            # ---------------------------------------------------------

            return {
                "request": request,

                "profile": profile,

                "future_events": _compact_events(
                    events
                ),

                "messages": _compact_messages(
                    messages
                ),

                "images": images,

                "image_context": image_context,

                "payment_options": (
                    _compact_payment_options(
                        payment_options
                    )
                ),
            }

        return [get_financial_context]


def _compact_events(
    events: list[dict],
) -> list[dict]:

    compacted = []

    for event in events:

        item = {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "description": event["description"],
            "category": event["category"],
            "direction": event["direction"],
            "amount": event["amount"],
            "currency": event["currency"],
            "event_date": event["event_date"],
            "settlement_date": event[
                "settlement_date"
            ],
            "status": event["status"],
            "flexibility": event["flexibility"],
            "minimum_allowed_amount": event[
                "minimum_allowed_amount"
            ],
        }

        # -------------------------------------------------------------
        # Preserve image-enrichment metadata when present.
        # -------------------------------------------------------------

        if event.get("amount_source") is not None:

            item["amount_source"] = (
                event["amount_source"]
            )

            item["source_image_id"] = (
                event.get("source_image_id")
            )

            item["image_confidence"] = (
                event.get("image_confidence")
            )

            item["image_currency"] = (
                event.get("image_currency")
            )

            item["image_evidence"] = (
                event.get("image_evidence")
            )

            item["image_amount_label"] = (
                event.get("image_amount_label")
            )

        compacted.append(item)

    return compacted


def _compact_messages(
    messages: list[dict],
) -> list[dict]:

    return [
        {
            "message_id": message["message_id"],
            "sent_at": message["sent_at"],
            "source_type": message["source_type"],
            "message_text": message["message_text"],
            "related_event_id": message[
                "related_event_id"
            ],
        }
        for message in messages
    ]


def _compact_payment_options(
    options: list[dict],
) -> list[dict]:

    return options