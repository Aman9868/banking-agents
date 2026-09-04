"""Wealth and Investment Advisory Subgraph."""

from agents.wealth.nodes import wealth_advisor_node
from agents.wealth.graph import wealth_graph_builder, wealth_subgraph
from agents.wealth.prompts import WEALTH_ADVISOR_SYSTEM_PROMPT, STUDENT_SIP_RECOMMENDATION_PROMPT

__all__ = [
    "wealth_advisor_node",
    "wealth_graph_builder",
    "wealth_subgraph",
    "WEALTH_ADVISOR_SYSTEM_PROMPT",
    "STUDENT_SIP_RECOMMENDATION_PROMPT",
]
