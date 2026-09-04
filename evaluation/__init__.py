"""Evaluation package for NovaBank Agent with LangSmith and LLM-as-a-Judge."""

from evaluation.dataset import DEFAULT_DATASET_NAME, BANKING_EVAL_EXAMPLES, create_or_sync_eval_dataset
from evaluation.evaluators import (
    hallucination_llm_judge_evaluator,
    intent_evaluator,
    widget_evaluator,
    financial_accuracy_evaluator,
    safety_evaluator
)

__all__ = [
    "DEFAULT_DATASET_NAME",
    "BANKING_EVAL_EXAMPLES",
    "create_or_sync_eval_dataset",
    "hallucination_llm_judge_evaluator",
    "intent_evaluator",
    "widget_evaluator",
    "financial_accuracy_evaluator",
    "safety_evaluator",
]

