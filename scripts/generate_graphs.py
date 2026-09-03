"""Utility script to generate and export all LangGraph architecture diagrams.

Usage:
    python scripts/generate_graphs.py
"""

from pathlib import Path
from agents.supervisor.graph import supervisor_graph_builder
from agents.account.graph import account_subgraph
from agents.transfer.graph import transfer_subgraph
from agents.card.graph import card_subgraph
from agents.loan.graph import loan_subgraph
from agents.payment.graph import payment_subgraph
from agents.support.graph import support_subgraph
from agents.insights.graph import insights_subgraph


def export_graphs():
    output_dir = Path("docs/graphs")
    output_dir.mkdir(parents=True, exist_ok=True)

    app = supervisor_graph_builder.compile()

    print("Generating full expanded graph (xray=True)...")
    expanded_png = app.get_graph(xray=True).draw_mermaid_png()
    (output_dir / "banking_graph_full.png").write_bytes(expanded_png)
    (output_dir / "banking_graph_full_expanded.png").write_bytes(expanded_png)
    Path("banking_graph.png").write_bytes(expanded_png)

    print("Generating high-level supervisor overview (xray=False)...")
    overview_png = app.get_graph(xray=False).draw_mermaid_png()
    (output_dir / "supervisor_overview.png").write_bytes(overview_png)

    # Subgraphs
    subgraphs = {
        "account_subgraph.png": account_subgraph,
        "transfer_subgraph.png": transfer_subgraph,
        "card_subgraph.png": card_subgraph,
        "loan_subgraph.png": loan_subgraph,
        "payment_subgraph.png": payment_subgraph,
        "support_subgraph.png": support_subgraph,
        "insights_subgraph.png": insights_subgraph,
    }

    for filename, sg in subgraphs.items():
        print(f"Generating {filename}...")
        sg_png = sg.get_graph().draw_mermaid_png()
        (output_dir / filename).write_bytes(sg_png)

    print("All graphs successfully updated in docs/graphs/")


if __name__ == "__main__":
    export_graphs()

