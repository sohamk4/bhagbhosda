import json
from typing import Any

from langchain_core.messages import SystemMessage

from .prompts import SYSTEM_PROMPT


MAX_TOOL_ITERATIONS = 5


def create_agent_node(llm):
    def agent_node(state: dict[str, Any]):
        messages = state.get("messages", [])

        iteration = state.get(
            "tool_iterations",
            0,
        )

        if iteration >= MAX_TOOL_ITERATIONS:
            raise RuntimeError(
                "Maximum financial-agent tool iterations exceeded."
            )

        system_message = SystemMessage(
            content=SYSTEM_PROMPT
        )

        response = llm.invoke(
            [system_message] + messages
        )

        return {
            "messages": [response],
            "tool_iterations": iteration + 1,
        }

    return agent_node


def extract_json_decision(message) -> dict[str, Any]:
    content = message.content

    if isinstance(content, list):
        content = "".join(
            item.get("text", "")
            if isinstance(item, dict)
            else str(item)
            for item in content
        )

    content = str(content).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    start = content.find("{")
    end = content.rfind("}")

    if start >= 0 and end > start:
        try:
            return json.loads(
                content[start:end + 1]
            )
        except json.JSONDecodeError:
            pass

    raise ValueError(
        "LLM did not return valid JSON."
    )