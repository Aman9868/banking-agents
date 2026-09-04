"""Loan Advisory, EMI Calculation, and Application Subgraph."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.loan.nodes import loan_orchestrator_node

loan_subgraph_builder = StateGraph(BankingSessionState)
loan_subgraph_builder.add_node("loan_orchestrator", loan_orchestrator_node)
loan_subgraph_builder.add_edge(START, "loan_orchestrator")
loan_subgraph_builder.add_edge("loan_orchestrator", END)

loan_subgraph = loan_subgraph_builder.compile()
