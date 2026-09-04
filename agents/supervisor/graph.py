"""Master Banking Supervisor StateGraph with 9-Agent Orchestration & Context Switching."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.account.graph import account_subgraph
from agents.transfer.graph import transfer_subgraph
from agents.card.graph import card_subgraph
from agents.loan.graph import loan_subgraph
from agents.payment.graph import payment_subgraph
from agents.support.graph import support_subgraph
from agents.insights.graph import insights_subgraph
from agents.wealth.graph import wealth_subgraph
from agents.policy.graph import policy_subgraph
from agents.supervisor.nodes import (
    supervisor_router_node,
    supervisor_dispatch,
    _build_interruption_continuation,
)

# Assemble Master Banking Supervisor Graph with all 9 Subgraphs
supervisor_graph_builder = StateGraph(BankingSessionState)
supervisor_graph_builder.add_node("router", supervisor_router_node)
supervisor_graph_builder.add_node("account_subgraph", account_subgraph)
supervisor_graph_builder.add_node("transfer_subgraph", transfer_subgraph)
supervisor_graph_builder.add_node("card_subgraph", card_subgraph)
supervisor_graph_builder.add_node("loan_subgraph", loan_subgraph)
supervisor_graph_builder.add_node("payment_subgraph", payment_subgraph)
supervisor_graph_builder.add_node("support_subgraph", support_subgraph)
supervisor_graph_builder.add_node("insights_subgraph", insights_subgraph)
supervisor_graph_builder.add_node("wealth_subgraph", wealth_subgraph)
supervisor_graph_builder.add_node("policy_subgraph", policy_subgraph)

supervisor_graph_builder.add_edge(START, "router")
supervisor_graph_builder.add_conditional_edges(
    "router",
    supervisor_dispatch,
    [
        "account_subgraph",
        "transfer_subgraph",
        "card_subgraph",
        "loan_subgraph",
        "payment_subgraph",
        "support_subgraph",
        "insights_subgraph",
        "wealth_subgraph",
        "policy_subgraph",
        END
    ]
)
supervisor_graph_builder.add_edge("account_subgraph", END)
supervisor_graph_builder.add_edge("transfer_subgraph", END)
supervisor_graph_builder.add_edge("card_subgraph", END)
supervisor_graph_builder.add_edge("loan_subgraph", END)
supervisor_graph_builder.add_edge("payment_subgraph", END)
supervisor_graph_builder.add_edge("support_subgraph", END)
supervisor_graph_builder.add_edge("insights_subgraph", END)
supervisor_graph_builder.add_edge("wealth_subgraph", END)
supervisor_graph_builder.add_edge("policy_subgraph", END)

supervisor_graph = supervisor_graph_builder.compile()
