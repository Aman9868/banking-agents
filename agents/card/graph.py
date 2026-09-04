"""Card Operations and Security Subgraph."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.card.nodes import card_action_node

card_subgraph_builder = StateGraph(BankingSessionState)
card_subgraph_builder.add_node("card_action", card_action_node)
card_subgraph_builder.add_edge(START, "card_action")
card_subgraph_builder.add_edge("card_action", END)

card_subgraph = card_subgraph_builder.compile()
