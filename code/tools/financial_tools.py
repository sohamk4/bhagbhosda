from langchain_core.tools import tool

from services.container import ServiceContainer


class FinancialTools:

    def __init__(self, services: ServiceContainer):
        self.services = services

    def get_tools(self):

        services = self.services

        @tool
        def get_user_profile(user_id: str) -> dict:
            """
            Get the user's financial profile.

            Returns home currency, current available balance,
            minimum balance to keep, financial priorities,
            protected categories, reducible categories,
            stoppable categories, accepted payment methods,
            and maximum installment months.
            """

            profile = services.profile.get_profile(user_id)

            if profile is None:
                raise ValueError(
                    f"No financial profile found for user_id={user_id}"
                )

            return profile

        @tool
        def get_financial_events(
            user_id: str,
            start_date: str | None = None,
            end_date: str | None = None,
            event_type: str | None = None,
            category: str | None = None,
            direction: str | None = None,
            status: str | None = None,
            limit: int | None = None,
        ) -> list[dict]:
            """
            Retrieve financial events for a user.

            Use this to inspect income, expenses, subscriptions,
            debt payments, refunds, investments, and other
            financial events.
            """

            return services.events.get_events(
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                category=category,
                direction=direction,
                status=status,
                limit=limit,
            )

        @tool
        def get_messages(
            user_id: str,
            request_id: str | None = None,
            related_event_id: str | None = None,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> list[dict]:
            """
            Retrieve financial-related messages for a user.

            Messages may contain important information about salary
            changes, bonuses, refunds, payroll, transfers, or other
            events that clarify or override structured financial data.
            """

            return services.messages.get_messages(
                user_id=user_id,
                request_id=request_id,
                related_event_id=related_event_id,
                start_date=start_date,
                end_date=end_date,
            )

        @tool
        def get_images(
            user_id: str,
            request_id: str | None = None,
            related_event_id: str | None = None,
        ) -> list[dict]:
            """
            Retrieve image references associated with a user,
            request, or financial event.
            """

            return services.images.get_images(
                user_id=user_id,
                request_id=request_id,
                related_event_id=related_event_id,
            )

        @tool
        def get_payment_options(
            request_id: str,
        ) -> list[dict]:
            """
            Retrieve the payment options explicitly provided for
            a financial request.
            """

            return services.payment_options.get_payment_options(
                request_id
            )

        @tool
        def get_exchange_rate(
            rate_date: str,
            from_currency: str,
            to_currency: str,
        ) -> float:
            """
            Get the fixed exchange rate for a specific date.
            """

            return services.exchange_rates.get_rate(
                rate_date=rate_date,
                from_currency=from_currency,
                to_currency=to_currency,
            )

        return [
            get_user_profile,
            get_financial_events,
            get_messages,
            get_images,
            get_payment_options,
            get_exchange_rate,
        ]