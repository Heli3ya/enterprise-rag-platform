"""
Configuration for the evaluation subsystem.

Everything is environment driven so the same image can run as a plain
inference service (evaluation disabled) or as a scheduled evaluation
worker without code changes.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_DATASET_PATH = PACKAGE_DIR / "dataset.jsonl"
DEFAULT_CORPUS_DIR = PACKAGE_DIR / "corpus"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "reports"

# Metrics the runner can compute. Keeping the list explicit means a typo
# in the environment variable fails loudly instead of silently producing
# a report with missing columns.
SUPPORTED_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "answer_correctness",
)

DEFAULT_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "answer_correctness",
)


def _env_flag(name, default=False):
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default, minimum=None):
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    if minimum is not None and value < minimum:
        return default

    return value


def _env_float(name, default, minimum=None):
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = float(raw)
    except ValueError:
        return default

    if minimum is not None and value < minimum:
        return default

    return value


def _env_int_list(name, default=()):
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return tuple(default)

    values = []

    for part in raw.replace(";", ",").split(","):
        part = part.strip()

        if not part:
            continue

        try:
            values.append(int(part))
        except ValueError:
            continue

    return tuple(values)


def _env_metrics(name, default=DEFAULT_METRICS):
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return tuple(default)

    requested = [
        part.strip().lower()
        for part in raw.split(",")
        if part.strip()
    ]

    selected = tuple(
        metric for metric in requested if metric in SUPPORTED_METRICS
    )

    return selected or tuple(default)


@dataclass(frozen=True)
class EvalConfig:
    """Immutable snapshot of the evaluation settings."""

    dataset_path: Path = DEFAULT_DATASET_PATH
    corpus_dir: Path = DEFAULT_CORPUS_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR

    metrics: tuple = DEFAULT_METRICS

    # How many chunks the retriever feeds the LLM. Mirrors the chat
    # pipeline so the evaluation measures the real configuration.
    top_k: int = 5

    # Judge behaviour. A CPU-only 3B model needs a generous timeout.
    judge_timeout: int = 180
    judge_retries: int = 1
    judge_question_count: int = 3

    # Ask the judge to decompose the answer into statements. Off by
    # default: sentence splitting is deterministic and small local
    # models over-decompose badly.
    llm_decomposition: bool = False

    # Acceptance thresholds used to compute `summary.passed`.
    min_faithfulness: float = 0.80
    min_answer_relevancy: float = 0.70
    min_context_precision: float = 0.60

    # Default retrieval scope when a run request does not specify one.
    default_tenant_id: int = None
    default_department_ids: tuple = ()

    # Maximum samples per run (0 = no cap). Useful on slow hardware.
    max_samples: int = 0

    # Scheduled runs.
    schedule_hours: float = 0.0
    schedule_limit: int = 10

    # Report retention, so the volume cannot grow without bound.
    keep_reports: int = 30

    # Shared secret for the internal endpoints. Empty means "open",
    # which is only acceptable because the service is internal-only.
    token: str = ""

    backend: str = "internal"

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls):
        backend = os.getenv("AI_EVAL_BACKEND", "internal").strip().lower()

        if backend not in {"internal", "ragas"}:
            backend = "internal"

        return cls(
            dataset_path=Path(
                os.getenv("AI_EVAL_DATASET_PATH", str(DEFAULT_DATASET_PATH))
            ),
            corpus_dir=Path(
                os.getenv("AI_EVAL_CORPUS_DIR", str(DEFAULT_CORPUS_DIR))
            ),
            output_dir=Path(
                os.getenv("AI_EVAL_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))
            ),
            metrics=_env_metrics("AI_EVAL_METRICS"),
            top_k=_env_int("AI_EVAL_TOP_K", 5, minimum=1),
            judge_timeout=_env_int("AI_EVAL_JUDGE_TIMEOUT", 180, minimum=10),
            judge_retries=_env_int("AI_EVAL_JUDGE_RETRIES", 1, minimum=0),
            judge_question_count=_env_int(
                "AI_EVAL_JUDGE_QUESTIONS",
                3,
                minimum=1,
            ),
            llm_decomposition=_env_flag(
                "AI_EVAL_LLM_DECOMPOSITION",
                False,
            ),
            min_faithfulness=_env_float(
                "AI_EVAL_MIN_FAITHFULNESS",
                0.80,
                minimum=0.0,
            ),
            min_answer_relevancy=_env_float(
                "AI_EVAL_MIN_ANSWER_RELEVANCY",
                0.70,
                minimum=0.0,
            ),
            min_context_precision=_env_float(
                "AI_EVAL_MIN_CONTEXT_PRECISION",
                0.60,
                minimum=0.0,
            ),
            default_tenant_id=_env_int("AI_EVAL_TENANT_ID", 0) or None,
            default_department_ids=_env_int_list(
                "AI_EVAL_DEPARTMENT_IDS"
            ),
            max_samples=_env_int("AI_EVAL_MAX_SAMPLES", 0, minimum=0),
            schedule_hours=_env_float(
                "AI_EVAL_SCHEDULE_HOURS",
                0.0,
                minimum=0.0,
            ),
            schedule_limit=_env_int("AI_EVAL_SCHEDULE_LIMIT", 10, minimum=1),
            keep_reports=_env_int("AI_EVAL_KEEP_REPORTS", 30, minimum=1),
            token=os.getenv("AI_EVAL_TOKEN", "").strip(),
            backend=backend,
        )

    def with_overrides(self, **overrides):
        """Return a copy with the given fields replaced."""

        clean = {
            key: value
            for key, value in overrides.items()
            if value is not None and hasattr(self, key)
        }

        if not clean:
            return self

        return self.__class__(**{**self.__dict__, **clean})

    @property
    def schedule_enabled(self):
        return self.schedule_hours > 0

    def thresholds(self):
        return {
            "faithfulness": self.min_faithfulness,
            "answer_relevancy": self.min_answer_relevancy,
            "context_precision": self.min_context_precision,
        }
