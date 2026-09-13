from services.container import ServiceContainer

from .calculation_tools import CalculationTools
from .context_tools import ContextTools


class ToolRegistry:

    def __init__(
        self,
        services: ServiceContainer,
    ):
        self.context_tools = ContextTools(
            services
        )

        self.calculation_tools = CalculationTools(
            services
        )

    def get_tools(self) -> list:
        return (
            self.context_tools.get_tools()
            + self.calculation_tools.get_tools()
        )