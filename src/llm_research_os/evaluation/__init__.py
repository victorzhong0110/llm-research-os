"""Real evaluation, comparison and human conclusions (R13).

A reported number here is computed from a fixed held-out set by a deterministic
evaluator and is reproducible from its own detail artifact. Comparisons refuse
incompatible setups, and conclusions are human judgements the system will not
supply.
"""

from llm_research_os.evaluation.compare import Comparison, ComparisonError, compare
from llm_research_os.evaluation.conclusion import Conclusion, ConclusionError, record
from llm_research_os.evaluation.evaluator import (
    EvaluationError,
    EvaluationResult,
    Example,
    evaluate,
    held_out_dataset,
    majority_baseline,
    recompute,
)

__all__ = [
    "Comparison",
    "ComparisonError",
    "Conclusion",
    "ConclusionError",
    "EvaluationError",
    "EvaluationResult",
    "Example",
    "compare",
    "evaluate",
    "held_out_dataset",
    "majority_baseline",
    "recompute",
    "record",
]
