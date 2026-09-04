"""Financial Insights, Spending Analytics, and Cashflow Forecasting Subgraph."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.insights.nodes import execute_insights_node

insights_subgraph_builder = StateGraph(BankingSessionState)
insights_subgraph_builder.add_node("execute_insights", execute_insights_node)
insights_subgraph_builder.add_edge(START, "execute_insights")
insights_subgraph_builder.add_edge("execute_insights", END)

insights_subgraph = insights_subgraph_builder.compile()
