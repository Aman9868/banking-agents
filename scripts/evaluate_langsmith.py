"""Automated LangSmith Evaluation and LLM-as-a-Judge Hallucination Benchmark Runner."""

import os
import sys
import argparse
import asyncio
from typing import Dict, Any
from dotenv import load_dotenv

# Ensure root directory is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(".env")

from langsmith import Client
from langsmith.evaluation import aevaluate
from langchain_core.messages import HumanMessage
from agents.state import BankingSessionState
from agents.supervisor.graph import supervisor_graph_builder
from evaluation.dataset import create_or_sync_eval_dataset, DEFAULT_DATASET_NAME, BANKING_EVAL_EXAMPLES
from evaluation.evaluators import (
    hallucination_llm_judge_evaluator,
    intent_evaluator,
    widget_evaluator,
    financial_accuracy_evaluator,
    safety_evaluator
)
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)

# Compile Master Supervisor StateGraph for evaluation
compiled_banking_graph = supervisor_graph_builder.compile()


async def predict_pipeline(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Target prediction pipeline for LangSmith evaluation.
    Invokes NovaBank's compiled supervisor graph with customer context.
    """
    query = inputs.get("query", "")
    cust_id = inputs.get("customer_id", 1)
    cust_name = inputs.get("customer_name", "Raju Sharma")

    logger.info("LangSmith evaluating banking query", query=query, customer_id=cust_id)

    state: BankingSessionState = {
        "messages": [HumanMessage(content=query)],
        "customer_id": cust_id,
        "customer_external_id": f"CUST-{cust_id:03d}",
        "customer_name": cust_name,
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "wealth_data": {},
        "policy_data": {},
        "current_intent": None,
        "current_sub_intent": None,
        "intent_confidence": None,
        "routing_reasoning": None,
        "negation_detected": None,
        "hitl_task_id": None,
        "hitl_status": None,
        "final_response": None,
        "customer_memory": {},
        "fraud_check_result": None,
        "aml_check_result": None,
        "ledger_check_result": None,
        "widget_type": None,
        "widget_data": None,
        "kyc_payload": None,
    }

    try:
        res = await compiled_banking_graph.ainvoke(state)
        final_answer = res.get("final_response") or (res.get("messages", [])[-1].content if res.get("messages") else "")
        return {
            "final_response": final_answer,
            "answer": final_answer,
            "intent": res.get("current_intent"),
            "sub_intent": res.get("current_sub_intent"),
            "widget_type": res.get("widget_type"),
            "widget_data": res.get("widget_data")
        }
    except Exception as exc:
        logger.error("Pipeline execution failed", error=str(exc))
        return {
            "final_response": f"⚠️ Internal evaluation error: {str(exc)}",
            "answer": f"Error: {str(exc)}",
            "intent": "ERROR",
            "widget_type": None
        }


async def main():
    parser = argparse.ArgumentParser(description="NovaBank LangSmith Evaluation and Hallucination Judge")
    parser.add_argument("--dataset", default=DEFAULT_DATASET_NAME, help="LangSmith dataset name")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of examples to evaluate")
    parser.add_argument("--sync-only", action="store_true", help="Sync dataset to LangSmith without running eval")
    parser.add_argument("--dry-run", action="store_true", help="Run local evaluation without connecting to LangSmith")
    args = parser.parse_args()

    api_key = os.getenv("LANGCHAIN_API_KEY") or settings.LANGCHAIN_API_KEY
    if not api_key and not args.dry_run:
        print("❌ Error: LANGCHAIN_API_KEY not found in environment or .env file.")
        sys.exit(1)

    print("=" * 70)
    print("🚀 NOVABANK AGENT — LANGSMITH TRACING & LLM JUDGE EVALUATION")
    print("=" * 70)
    print(f"• Dataset: {args.dataset}")
    print(f"• Project: {os.getenv('LANGCHAIN_PROJECT', 'novabank-agent-prod')}")
    print(f"• Evaluators: [Hallucination LLM Judge, Intent Match, Widget, Financial, Safety]")

    if args.dry_run:
        print("\n⚙️ Running in LOCAL DRY-RUN MODE (Evaluating without remote LangSmith push)...")
        examples = BANKING_EVAL_EXAMPLES[:args.limit] if args.limit else BANKING_EVAL_EXAMPLES
        passed = 0
        for i, ex in enumerate(examples, 1):
            inp = ex["inputs"]
            exp = ex["outputs"]
            print(f"\n[{i}/{len(examples)}] Query: \"{inp['query']}\"")
            pred = await predict_pipeline(inp)
            print(f"   ➔ Intent: {pred.get('intent')} (Expected: {exp.get('intent')})")
            print(f"   ➔ Widget: {pred.get('widget_type')} (Expected: {exp.get('widget_type')})")
            print(f"   ➔ Response: {pred.get('final_response')[:90]}...")

            # Run evaluators
            class DummyRun:
                outputs = pred
            class DummyExample:
                inputs = inp
                outputs = exp

            run_obj = DummyRun()
            ex_obj = DummyExample()

            i_res = intent_evaluator(run_obj, ex_obj)
            w_res = widget_evaluator(run_obj, ex_obj)
            f_res = financial_accuracy_evaluator(run_obj, ex_obj)
            s_res = safety_evaluator(run_obj, ex_obj)
            h_res = await hallucination_llm_judge_evaluator(run_obj, ex_obj)

            print(f"   ⚖️ Evaluator Scores:")
            print(f"      • Intent Accuracy:      {i_res['score']*100:.0f}%")
            print(f"      • Widget Match:         {w_res['score']*100:.0f}%")
            print(f"      • Financial Precision:  {f_res['score']*100:.0f}%")
            print(f"      • Security & Safety:    {s_res['score']*100:.0f}%")
            print(f"      • Hallucination Judge:  {h_res['score']*100:.0f}% ({h_res['comment'][:60]})")

            if i_res['score'] >= 0.8 and s_res['score'] == 1.0 and h_res['score'] == 1.0:
                passed += 1

        print(f"\n🎯 Local Evaluation Result: {passed}/{len(examples)} test cases passed successfully.")
        return

    # Remote LangSmith Evaluation
    client = Client()
    print("\n📡 Connecting to LangSmith at https://api.smith.langchain.com ...")
    create_or_sync_eval_dataset(client, dataset_name=args.dataset)

    if args.sync_only:
        print("✅ Dataset synced successfully to LangSmith! Exiting (--sync-only).")
        return

    print("📊 Executing LangSmith aevaluate() with LLM-as-a-Judge...")
    experiment_results = await aevaluate(
        predict_pipeline,
        data=args.dataset,
        evaluators=[
            hallucination_llm_judge_evaluator,
            intent_evaluator,
            widget_evaluator,
            financial_accuracy_evaluator,
            safety_evaluator
        ],
        experiment_prefix="novabank-agent-eval",
        max_concurrency=2,
        metadata={
            "app": "NovaBank Multi-Agent Banking System",
            "version": "2.0.0",
            "supervisor": "LangGraph StateGraph",
            "llm_judge": "Groq Llama-3.3-70b / Gemini"
        }
    )

    print("\n" + "=" * 70)
    print("✅ EVALUATION COMPLETE!")
    print("Check your LangSmith Dashboard for full traces, latencies, and judge feedback:")
    print("👉 https://smith.langchain.com/")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

