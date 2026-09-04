"""Policy, Insurance Advisory, and Government Schemes Subgraph."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.policy.nodes import policy_orchestrator_node

policy_graph_builder = StateGraph(BankingSessionState)
policy_graph_builder.add_node("policy_orchestrator", policy_orchestrator_node)
policy_graph_builder.add_edge(START, "policy_orchestrator")
policy_graph_builder.add_edge("policy_orchestrator", END)
policy_subgraph = policy_graph_builder.compile()
