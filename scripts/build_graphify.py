"""AST-based Knowledge Graph builder for the Banking Agent codebase.

Generates the standard Graphify outputs:
- graphify-out/graph.json
- graphify-out/GRAPH_REPORT.md
- graphify-out/graph.html (interactive D3 graph visualizer)
"""

import os
import ast
import json
from pathlib import Path
from collections import defaultdict


def analyze_repository(repo_path: Path):
    nodes = {}
    edges = []
    file_stats = {}

    target_dirs = ["agents", "apps", "database", "gateway", "policies", "security", "services", "tools", "tests"]
    
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in [".venv", "venv", "__pycache__", ".git", ".pytest_cache", "node_modules", "dist", "build"]]
        
        rel_root = Path(root).relative_to(repo_path)
        first_part = rel_root.parts[0] if rel_root.parts else ""
        if first_part not in target_dirs and first_part != "":
            continue

        for file in files:
            if not file.endswith(".py"):
                continue
            file_path = Path(root) / file
            rel_path = str(file_path.relative_to(repo_path))
            
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=rel_path)
            except Exception:
                continue

            community = rel_path.split("/")[0]
            module_id = rel_path
            docstring = ast.get_docstring(tree) or ""
            summary = docstring.strip().split("\n")[0] if docstring else f"Module {rel_path}"
            
            functions = []
            classes = []
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    imports.append(mod)

            file_stats[rel_path] = {
                "lines": len(content.splitlines()),
                "functions": functions,
                "classes": classes,
                "imports": imports,
                "community": community,
                "summary": summary
            }

            nodes[module_id] = {
                "id": module_id,
                "label": Path(rel_path).name,
                "type": "file",
                "community": community,
                "summary": summary,
                "functions": functions,
                "classes": classes,
                "lines": len(content.splitlines()),
                "in_degree": 0,
                "out_degree": 0
            }

    for src_path, stats in file_stats.items():
        for imp in stats["imports"]:
            for target_path in file_stats.keys():
                mod_key = target_path.replace("/", ".").replace(".py", "")
                if mod_key.endswith(".__init__"):
                    mod_key = mod_key[:-9]
                
                if imp == mod_key or (imp and mod_key.startswith(imp) and imp.split(".")[0] in target_dirs):
                    if src_path != target_path:
                        edges.append({
                            "source": src_path,
                            "target": target_path,
                            "relation": "imports"
                        })
                        nodes[src_path]["out_degree"] += 1
                        nodes[target_path]["in_degree"] += 1
                    break

    for node in nodes.values():
        node["total_degree"] = node["in_degree"] + node["out_degree"]

    sorted_nodes = sorted(nodes.values(), key=lambda x: x["total_degree"], reverse=True)
    god_nodes = sorted_nodes[:8]

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "god_nodes": god_nodes,
        "file_stats": file_stats
    }


def generate_graph_report_md(data) -> str:
    god_nodes_md = "\n".join([
        f"- **`{gn['id']}`** (Degree: {gn['total_degree']} | In: {gn['in_degree']}, Out: {gn['out_degree']})\n"
        f"  - *Role*: {gn['summary']}\n"
        f"  - *Key Symbols*: {', '.join((gn['classes'] + gn['functions'])[:6])}"
        for gn in data["god_nodes"]
    ])

    communities = defaultdict(list)
    for n in data["nodes"]:
        communities[n["community"]].append(n)

    communities_md = ""
    for comm, n_list in sorted(communities.items()):
        communities_md += f"\n### Community: `{comm}` ({len(n_list)} files)\n"
        for n in sorted(n_list, key=lambda x: x["total_degree"], reverse=True)[:5]:
            communities_md += f"- **`{n['id']}`**: {n['summary']} *(Symbols: {len(n['functions']) + len(n['classes'])})*\n"

    report = f"""# Codebase Knowledge Graph Report (Graphify)

*Generated for AI Coding Agents (Cursor, Claude Code, Antigravity, Copilot, Codex, Windsurf, Aider)*

---

## 1. Executive Architecture Summary
The **AI Banking Agent** platform is a multi-agent hierarchical state machine built on **LangGraph**. 
- **Total Mapped Files**: {len(data["nodes"])}
- **Total Dependency Relationships**: {len(data["edges"])}
- **Root Orchestrator**: `agents/supervisor/graph.py`

---

## 2. Identified "God Nodes" (Core Architectural Hubs)
> **WARNING FOR AI AGENTS**: Modifying any of these core nodes carries a high blast radius. Always check dependent modules before refactoring!

{god_nodes_md}

---

## 3. Subgraph Communities & Responsibilities
{communities_md}

---

## 4. Multi-Agent Dispatch Topology
The system dispatches through `agents/supervisor/graph.py`:
1. **`account_subgraph`** (`agents/account/graph.py`): KYC slot collection, age validation (18+), AML screening, HITL approval.
2. **`transfer_subgraph`** (`agents/transfer/graph.py`): Entity resolution, parallel fraud + AML + ledger check, 2-phase confirmation.
3. **`card_subgraph`** (`agents/card/graph.py`): Instant card freeze/unfreeze, limit adjustments, stolen replacement.
4. **`loan_subgraph`** (`agents/loan/graph.py`): Mathematical EMI calculation, DTI threshold verification, loan application.
5. **`payment_subgraph`** (`agents/payment/graph.py`): Biller directory, bill fetching, UPI VPA verification, settlement.
6. **`support_subgraph`** (`agents/support/graph.py`): Decline reason investigation, policy RAG, ticket generation.
7. **`insights_subgraph`** (`agents/insights/graph.py`): Spending analytics, categorization, trend alerts.

---

## 5. Blast Radius & Change Guidance for AI Agents
- **Changing Session State**: Modify `agents/state.py` carefully. All 7 subgraphs share `BankingSessionState`.
- **Modifying Intent Routing**: Test against `tests/unit/test_production_intent_router.py`.
- **Database Schema Changes**: Ensure both `database/models/banking.py` and `database/repositories/banking_repo.py` are kept in lockstep.
- **Executing Transfers or Payments**: Always enforce two-phase confirmation and pass through `gateway/tool_gateway/gateway.py` for idempotency and audit logs.
"""
    return report


def generate_graph_html(data) -> str:
    nodes_json = json.dumps(data["nodes"])
    edges_json = json.dumps(data["edges"])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Banking Agent Codebase Knowledge Graph</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            overflow: hidden;
        }}
        #header {{
            position: absolute;
            top: 16px;
            left: 20px;
            z-index: 10;
            background: rgba(15, 23, 42, 0.85);
            padding: 12px 20px;
            border-radius: 8px;
            border: 1px solid #334155;
            backdrop-filter: blur(8px);
        }}
        #header h1 {{
            margin: 0 0 6px 0;
            font-size: 18px;
            font-weight: 600;
            color: #38bdf8;
        }}
        #header p {{
            margin: 0;
            font-size: 12px;
            color: #94a3b8;
        }}
        #sidebar {{
            position: absolute;
            top: 16px;
            right: 20px;
            width: 320px;
            max-height: calc(100vh - 50px);
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px;
            box-sizing: border-box;
            overflow-y: auto;
            display: none;
            backdrop-filter: blur(8px);
            font-size: 13px;
        }}
        #sidebar h3 {{
            margin: 0 0 8px 0;
            color: #38bdf8;
            word-break: break-all;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            margin-bottom: 8px;
            background: #1e293b;
            color: #cbd5e1;
        }}
        .node circle {{
            stroke-width: 2px;
            cursor: pointer;
            transition: r 0.2s;
        }}
        .node text {{
            font-size: 10px;
            fill: #cbd5e1;
            pointer-events: none;
        }}
        .link {{
            stroke: #475569;
            stroke-opacity: 0.5;
            stroke-width: 1.2px;
        }}
    </style>
</head>
<body>
    <div id="header">
        <h1>Banking Agent Codebase Graph</h1>
        <p>Dynamic dependency map & multi-agent architecture • Click any node to inspect</p>
    </div>
    <div id="sidebar"></div>
    <svg id="graph" width="100%" height="100vh"></svg>

    <script>
        const nodesData = {nodes_json};
        const linksData = {edges_json};

        const width = window.innerWidth;
        const height = window.innerHeight;

        const colorMap = {{
            "agents": "#818cf8",
            "gateway": "#38bdf8",
            "database": "#34d399",
            "apps": "#fbbf24",
            "policies": "#f472b6",
            "services": "#a78bfa",
            "security": "#f87171",
            "tools": "#fb923c",
            "tests": "#94a3b8"
        }};

        const svg = d3.select("#graph")
            .attr("width", width)
            .attr("height", height);

        const g = svg.append("g");

        svg.call(d3.zoom()
            .scaleExtent([0.2, 5])
            .on("zoom", (event) => g.attr("transform", event.transform)));

        const simulation = d3.forceSimulation(nodesData)
            .force("link", d3.forceLink(linksData).id(d => d.id).distance(70))
            .force("charge", d3.forceManyBody().strength(-140))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(d => Math.max(10, d.total_degree * 2 + 8)));

        const link = g.append("g")
            .attr("class", "links")
            .selectAll("line")
            .data(linksData)
            .enter().append("line")
            .attr("class", "link");

        const node = g.append("g")
            .attr("class", "nodes")
            .selectAll("g")
            .data(nodesData)
            .enter().append("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        node.append("circle")
            .attr("r", d => Math.max(6, Math.min(22, d.total_degree * 1.8 + 5)))
            .attr("fill", d => colorMap[d.community] || "#64748b")
            .attr("stroke", d => d.total_degree > 6 ? "#fbbf24" : "#1e293b")
            .attr("stroke-width", d => d.total_degree > 6 ? 3 : 1.5);

        node.append("text")
            .attr("dx", 12)
            .attr("dy", 4)
            .text(d => d.label);

        node.on("click", (event, d) => {{
            const sidebar = document.getElementById("sidebar");
            sidebar.style.display = "block";
            sidebar.innerHTML = `
                <h3>${{d.id}}</h3>
                <span class="badge" style="background:${{colorMap[d.community] || '#334155'}}22; color:${{colorMap[d.community] || '#fff'}}">${{d.community.toUpperCase()}}</span>
                <p style="margin: 8px 0; color: #cbd5e1;">${{d.summary}}</p>
                <div style="margin: 10px 0; padding: 8px; background: #1e293b; border-radius: 6px;">
                    <div><strong>Total Connections:</strong> ${{d.total_degree}} (In: ${{d.in_degree}}, Out: ${{d.out_degree}})</div>
                    <div><strong>Lines:</strong> ${{d.lines}}</div>
                </div>
                ${{d.classes.length ? `<div><strong>Classes:</strong><ul style="margin:4px 0 8px 18px; padding:0;">${{d.classes.map(c => `<li><code>${{c}}</code></li>`).join("")}}</ul></div>` : ""}}
                ${{d.functions.length ? `<div><strong>Functions:</strong><ul style="margin:4px 0 8px 18px; padding:0;">${{d.functions.slice(0, 10).map(f => `<li><code>${{f}}</code></li>`).join("")}}${{d.functions.length > 10 ? `<li><em>+${{d.functions.length - 10}} more</em></li>` : ""}}</ul></div>` : ""}}
            `;
        }});

        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
        }});

        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}
    </script>
</body>
</html>
"""
    return html


def main():
    repo_path = Path(__file__).resolve().parent.parent
    out_dir = repo_path / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning codebase at {repo_path}...")
    data = analyze_repository(repo_path)

    graph_json_path = out_dir / "graph.json"
    with open(graph_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    report_md = generate_graph_report_md(data)
    graph_report_path = out_dir / "GRAPH_REPORT.md"
    graph_report_path.write_text(report_md, encoding="utf-8")

    html_content = generate_graph_html(data)
    graph_html_path = out_dir / "graph.html"
    graph_html_path.write_text(html_content, encoding="utf-8")

    print("Graphify artifacts successfully generated!")


if __name__ == "__main__":
    main()

