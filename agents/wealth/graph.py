"""Wealth, SIP Investment Advisory, and Live Market Search Subgraph."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.wealth.nodes import wealth_advisor_node

wealth_graph_builder = StateGraph(BankingSessionState)
wealth_graph_builder.add_node("wealth_advisor", wealth_advisor_node)
wealth_graph_builder.add_edge(START, "wealth_advisor")
wealth_graph_builder.add_edge("wealth_advisor", END)
wealth_subgraph = wealth_graph_builder.compile()
