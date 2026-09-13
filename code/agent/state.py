from typing import Any

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    request_id: str
    user_id: str

    request: dict[str, Any]

    messages: list[Any]

    financial_result: dict[str, Any] | None
    payment_result: dict[str, Any] | None

    final_decision: dict[str, Any] | None

    validation_result: dict[str, Any] | None

    tool_iterations: int