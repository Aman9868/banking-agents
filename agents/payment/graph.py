"""Bill Payments and UPI Subgraph with Two-Phase Confirmation and Idempotency."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.payment.nodes import payment_orchestrator_node

payment_subgraph_builder = StateGraph(BankingSessionState)
payment_subgraph_builder.add_node("payment_orchestrator", payment_orchestrator_node)
payment_subgraph_builder.add_edge(START, "payment_orchestrator")
payment_subgraph_builder.add_edge("payment_orchestrator", END)

payment_subgraph = payment_subgraph_builder.compile()
