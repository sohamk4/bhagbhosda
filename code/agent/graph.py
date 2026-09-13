from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from engine.validator import DecisionValidator

from .nodes import (
    create_agent_node,
    extract_json_decision,
)
from .state import AgentState


def create_financial_graph(
    llm,
    tools,
):
    llm_with_tools = llm.bind_tools(tools)

    builder = StateGraph(
        AgentState
    )

    agent_node = create_agent_node(
        llm_with_tools
    )

    tool_node = ToolNode(tools)

    builder.add_node(
        "agent",
        agent_node,
    )

    builder.add_node(
        "tools",
        tool_node,
    )

    builder.add_edge(
        START,
        "agent",
    )

    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: END,
        },
    )

    builder.add_edge(
        "tools",
        "agent",
    )

    return builder.compile()