from typing import Any

from langchain_core.tools import tool

from engine.affordability import AffordabilityEngine
from engine.forecast import ForecastEngine
from engine.payment_plans import PaymentPlanEngine


class CalculationTools:

    def __init__(self, services):
        self.services = services

        self.forecast_engine = ForecastEngine(
            services
        )

        self.affordability_engine = AffordabilityEngine(
            services
        )

        self.payment_plan_engine = PaymentPlanEngine(
            services
        )

    def get_tools(self) -> list:

        services = self.services
        forecast_engine = self.forecast_engine
        affordability_engine = self.affordability_engine
        payment_plan_engine = self.payment_plan_engine

        @tool
        def forecast_financial_position(
            user_id: str,
            request_id: str,
        ) -> dict[str, Any]:
            """
            Forecast the user's financial position for the
            90-day safety window.

            The tool retrieves all required financial data itself.
            The caller must not provide balances, income totals,
            or expense totals.
            """

            return forecast_engine.forecast(
                user_id=user_id,
                request_id=request_id,
            )

        @tool
        def evaluate_affordability(
            user_id: str,
            request_id: str,
        ) -> dict[str, Any]:
            """
            Determine how much of a requested expense can safely
            be paid and whether the request is affordable.
            """

            return affordability_engine.evaluate(
                user_id=user_id,
                request_id=request_id,
            )

        @tool
        def evaluate_payment_options(
            user_id: str,
            request_id: str,
        ) -> dict[str, Any]:
            """
            Evaluate the payment options supplied for the request.

            Only payment methods accepted by the user's profile
            are considered.
            """

            return payment_plan_engine.evaluate(
                user_id=user_id,
                request_id=request_id,
            )

        return [
            forecast_financial_position,
            evaluate_affordability,
            evaluate_payment_options,
        ]