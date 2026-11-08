"""
Offline RAG quality evaluation for the AI inference service.

The package mirrors the metrics defined by RAGAS (faithfulness, answer
relevancy, context precision, answer correctness) but implements them on
top of the service's own LLM client and embedding model. That keeps the
evaluation runnable on an air-gapped deployment and avoids pulling the
large ``ragas`` dependency tree into the inference image.

If the ``ragas`` package is installed and ``AI_EVAL_BACKEND=ragas``, the
:mod:`evaluation.ragas_backend` adapter is used instead; the report
format stays identical so dashboards do not care which backend ran.
"""

from .config import EvalConfig
from .dataset import EvalSample, DatasetError, load_dataset
from .runner import EvaluationRunner, RunRequest

__all__ = [
    "EvalConfig",
    "EvalSample",
    "DatasetError",
    "load_dataset",
    "EvaluationRunner",
    "RunRequest",
]
