"""Customer Support Subgraph with Transaction Dispute Analysis, Grounded RAG, and Human Escalation."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.support.nodes import support_orchestrator_node

support_subgraph_builder = StateGraph(BankingSessionState)
support_subgraph_builder.add_node("support_orchestrator", support_orchestrator_node)
support_subgraph_builder.add_edge(START, "support_orchestrator")
support_subgraph_builder.add_edge("support_orchestrator", END)

support_subgraph = support_subgraph_builder.compile()
