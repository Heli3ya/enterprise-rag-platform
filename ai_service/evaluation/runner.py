"""
Evaluation runner.

For every ground-truth sample the runner:

1. runs the production hybrid retrieval (vector + keyword + rerank),
2. builds the production RAG prompt and asks the LLM for an answer,
3. scores the answer with the requested metrics,
4. writes a structured JSON and CSV report.

The runner is deliberately synchronous and single-threaded by default.
The local model is CPU bound and already serialised behind the service's
inference lock, so extra threads would only add context switching. For a
GPU or a remote OpenAI-compatible endpoint set ``AI_EVAL_CONCURRENCY``.
"""

import csv
import json
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import EvalConfig, SUPPORTED_METRICS
from .dataset import (
    DatasetError,
    dataset_summary,
    load_dataset,
    select_samples,
)
from .judge import LLMJudge
from .metrics import score_sample
from .prompt import build_rag_prompt
from .retrieval import format_contexts, retrieve


REPORT_VERSION = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunRequest:
    """A single evaluation run, as posted to /api/eval/run/."""

    tenant_id: int = None
    department_ids: tuple = ()
    limit: int = None
    sample_ids: tuple = ()
    metrics: tuple = ()
    dataset_path: Path = None
    top_k: int = None
    triggered_by: str = "api"

    def resolve(self, config):
        """Merge the request with the environment defaults."""

        tenant_id = self.tenant_id or config.default_tenant_id
        department_ids = tuple(self.department_ids) or config.default_department_ids

        metrics = tuple(
            metric
            for metric in (self.metrics or config.metrics)
            if metric in SUPPORTED_METRICS
        )

        limit = self.limit

        if limit is None and config.max_samples:
            limit = config.max_samples

        return {
            "tenant_id": tenant_id,
            "department_ids": department_ids,
            "metrics": metrics or config.metrics,
            "limit": limit,
            "sample_ids": tuple(self.sample_ids),
            "dataset_path": Path(self.dataset_path or config.dataset_path),
            "top_k": self.top_k or config.top_k,
            "triggered_by": self.triggered_by,
        }


class RunError(RuntimeError):
    """The run could not start (bad scope, empty dataset, ...)."""


def _mean(values):
    return round(statistics.fmean(values), 4) if values else None


def _summarize(samples, metrics, thresholds):
    summary = {}

    for metric in metrics:
        scores = []
        methods = {}

        for sample in samples:
            result = (sample.get("scores") or {}).get(metric)

            if not result or result.get("score") is None:
                continue

            if sample.get("error"):
                continue

            scores.append(float(result["score"]))
            method = result.get("method", "unknown")
            methods[method] = methods.get(method, 0) + 1

        entry = {
            "mean": _mean(scores),
            "median": round(statistics.median(scores), 4) if scores else None,
            "min": round(min(scores), 4) if scores else None,
            "max": round(max(scores), 4) if scores else None,
            "count": len(scores),
            "methods": methods,
        }

        threshold = thresholds.get(metric)

        if threshold is not None:
            entry["threshold"] = threshold
            entry["passed"] = (
                entry["mean"] is not None and entry["mean"] >= threshold
            )

        summary[metric] = entry

    checks = [
        entry["passed"]
        for entry in summary.values()
        if entry.get("passed") is not None
    ]

    summary["passed"] = all(checks) if checks else None
    summary["checks_run"] = len(checks)
    summary["checks_passed"] = sum(1 for flag in checks if flag)

    return summary


class EvaluationRunner:
    """Turns a dataset into a scored report."""

    def __init__(
        self,
        config=None,
        *,
        llm_client,
        embedder=None,
        embed_query=None,
        reranker=None,
        connection_factory=None,
        connection_releaser=None,
        logger=None,
    ):
        self.config = config or EvalConfig.from_env()
        self.llm_client = llm_client
        self._embedder = embedder
        self._embed_query = embed_query
        self._reranker = reranker
        self._connection_factory = connection_factory
        self._connection_releaser = connection_releaser
        self.logger = logger

    # -- helpers --------------------------------------------------------

    def _log(self, level, message, *args):
        if self.logger is not None:
            getattr(self.logger, level, self.logger.info)(message, *args)

    def _embed(self, texts):
        if self._embedder is None:
            raise RunError("No embedding function is configured.")

        return self._embedder(list(texts))

    def _embed_one(self, text):
        if self._embed_query is not None:
            return self._embed_query(text)

        return self._embed([text])[0]

    def _answer(self, prompt):
        """Ask the LLM for a complete, non-streamed answer."""

        return self.llm_client.generate_with_options(
            prompt,
            temperature=0.0,
            max_tokens=768,
            timeout=self.config.judge_timeout,
            seed=11,
        )

    # -- report writing -------------------------------------------------

    def _prepare_output_dir(self):
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _prune_reports(self, output_dir):
        keep = max(1, self.config.keep_reports)
        reports = sorted(
            output_dir.glob("report_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        for stale in reports[keep:]:
            for suffix in (".json", ".csv"):
                candidate = stale.with_suffix(suffix)

                try:
                    if candidate.exists():
                        candidate.unlink()
                except OSError:  # pragma: no cover - filesystem edge case
                    pass

    def _write_reports(self, output_dir, report):
        run_id = report["run_id"]
        json_path = output_dir / f"report_{run_id}.json"
        csv_path = output_dir / f"report_{run_id}.csv"

        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        metrics = report["config"]["metrics"]

        fieldnames = [
            "id",
            "question",
            "ground_truth",
            "answer",
            "contexts_count",
            "top_document",
            *metrics,
            "faithfulness_method",
            "latency_ms",
            "error",
        ]

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            for sample in report["samples"]:
                scores = sample.get("scores") or {}
                row = {
                    "id": sample["id"],
                    "question": sample["question"],
                    "ground_truth": sample["ground_truth"],
                    "answer": sample["answer"],
                    "contexts_count": len(sample.get("contexts") or []),
                    "top_document": (
                        (sample.get("contexts") or [{}])[0].get(
                            "document_title",
                            "",
                        )
                    ),
                    "faithfulness_method": (
                        (scores.get("faithfulness") or {}).get("method", "")
                    ),
                    "latency_ms": (sample.get("latency_ms") or {}).get(
                        "total",
                        "",
                    ),
                    "error": sample.get("error") or "",
                }

                for metric in metrics:
                    row[metric] = (scores.get(metric) or {}).get("score", "")

                writer.writerow(row)

        # Pointers so a dashboard can always read the newest run without
        # having to list the directory.
        (output_dir / "latest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "latest_summary.json").write_text(
            json.dumps(
                {
                    "run_id": report["run_id"],
                    "finished_at": report["finished_at"],
                    "summary": report["summary"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._prune_reports(output_dir)

        return {
            "json": str(json_path),
            "csv": str(csv_path),
            "summary": str(output_dir / "latest_summary.json"),
        }

    # -- main entry point -----------------------------------------------

    def run(self, request=None, *, progress=None):
        request = request or RunRequest()
        scope = request.resolve(self.config)

        tenant_id = scope["tenant_id"]
        department_ids = scope["department_ids"]

        if tenant_id is None:
            raise RunError(
                "No tenant scope. Pass tenant_id or set AI_EVAL_TENANT_ID."
            )

        if not department_ids:
            raise RunError(
                "No department scope. Pass department_ids or set "
                "AI_EVAL_DEPARTMENT_IDS."
            )

        samples = select_samples(
            load_dataset(scope["dataset_path"]),
            limit=scope["limit"],
            sample_ids=scope["sample_ids"],
        )

        if not samples:
            raise DatasetError("The dataset selection is empty.")

        metrics = scope["metrics"]
        judge = LLMJudge(
            self.llm_client,
            timeout=self.config.judge_timeout,
            retries=self.config.judge_retries,
            question_count=self.config.judge_question_count,
        )

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        started_at = _now_iso()
        started_monotonic = time.monotonic()

        self._log(
            "info",
            "Evaluation run %s started: %s samples, metrics=%s",
            run_id,
            len(samples),
            ",".join(metrics),
        )

        connection = None
        discard_connection = False
        evaluated = []

        try:
            if self._connection_factory is None:
                raise RunError("No database connection factory is configured.")

            connection = self._connection_factory()

            for index, sample in enumerate(samples, start=1):
                evaluated.append(
                    self._evaluate_sample(
                        connection,
                        sample,
                        metrics=metrics,
                        judge=judge,
                        tenant_id=tenant_id,
                        department_ids=department_ids,
                        top_k=scope["top_k"],
                    )
                )

                if progress is not None:
                    try:
                        progress(index, len(samples), sample.id)
                    except Exception:  # pragma: no cover - callback safety
                        pass

        except Exception:
            discard_connection = connection is not None
            raise

        finally:
            if connection is not None and self._connection_releaser is not None:
                try:
                    self._connection_releaser(
                        connection,
                        discard=discard_connection,
                    )
                except Exception:  # pragma: no cover - cleanup safety
                    pass

        finished_at = _now_iso()
        duration = round(time.monotonic() - started_monotonic, 2)

        backend_note = None

        if self.config.backend == "ragas":
            backend_note = self._apply_ragas_backend(evaluated, metrics)

        # Full chunk text is only needed while scoring; keeping it in the
        # report would multiply its size for no diagnostic benefit.
        for sample in evaluated:
            sample.pop("_full_contexts", None)

        summary = _summarize(evaluated, metrics, self.config.thresholds())

        report = {
            "report_version": REPORT_VERSION,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration,
            "backend": self.config.backend,
            "backend_note": backend_note,
            "config": {
                "tenant_id": tenant_id,
                "department_ids": list(department_ids),
                "metrics": list(metrics),
                "top_k": scope["top_k"],
                "limit": scope["limit"],
                "triggered_by": scope["triggered_by"],
                "judge_timeout": self.config.judge_timeout,
                "dataset_path": str(scope["dataset_path"]),
            },
            "dataset": dataset_summary(samples),
            "judge": {
                "provider": getattr(self.llm_client, "provider", "unknown"),
                "model": getattr(self.llm_client, "model", "unknown"),
            },
            "summary": summary,
            "samples": evaluated,
        }

        output_dir = self._prepare_output_dir()

        # The paths are part of the report itself, so they must be set
        # before the files are written.
        report["report_paths"] = {
            "json": str(output_dir / f"report_{run_id}.json"),
            "csv": str(output_dir / f"report_{run_id}.csv"),
            "summary": str(output_dir / "latest_summary.json"),
        }

        self._write_reports(output_dir, report)

        self._log(
            "info",
            "Evaluation run %s finished in %ss: %s",
            run_id,
            duration,
            {
                metric: summary[metric]["mean"]
                for metric in metrics
            },
        )

        return report

    def _apply_ragas_backend(self, evaluated, metrics):
        """
        Re-score every sample with the upstream ragas implementation.

        Failure is never fatal: the internal scores stay in place and the
        reason is recorded in the report.
        """

        from . import ragas_backend

        if not ragas_backend.is_available():
            self._log(
                "warning",
                "AI_EVAL_BACKEND=ragas but the ragas package is missing; "
                "keeping internal metrics.",
            )
            return "ragas is not installed; internal metrics were used."

        rows = [
            {
                "question": sample["question"],
                "answer": sample.get("answer") or "",
                "contexts": sample.get("_full_contexts") or [],
                "ground_truth": sample.get("ground_truth") or "",
            }
            for sample in evaluated
        ]

        try:
            scores = ragas_backend.evaluate_batch(
                rows,
                metrics=metrics,
                llm_client=self.llm_client,
                embedder=self._embed,
                timeout=self.config.judge_timeout,
            )
        except Exception as exc:
            self._log(
                "warning",
                "ragas evaluation failed, keeping internal metrics: %s",
                exc,
            )
            return f"ragas failed: {type(exc).__name__}: {exc}"[:300]

        replaced = 0

        for index, row_scores in scores.items():
            for metric, value in row_scores.items():
                evaluated[index].setdefault("scores", {})[metric] = {
                    "score": round(float(value), 4),
                    "method": "ragas",
                }
                replaced += 1

        return f"ragas scored {len(scores)} samples ({replaced} metric values)."

    def _evaluate_sample(
        self,
        connection,
        sample,
        *,
        metrics,
        judge,
        tenant_id,
        department_ids,
        top_k,
    ):
        started = time.monotonic()
        entry = {
            "id": sample.id,
            "question": sample.question,
            "ground_truth": sample.ground_truth,
            "document": sample.document,
            "tags": list(sample.tags),
            "answer": "",
            "contexts": [],
            "_full_contexts": [],
            "scores": {},
            "latency_ms": {},
            "error": None,
        }

        try:
            retrieval_started = time.monotonic()

            results = retrieve(
                connection,
                sample.question,
                tenant_id=tenant_id,
                department_ids=department_ids,
                limit=top_k,
                embed_query=self._embed_one,
                rerank=self._reranker,
            )

            retrieval_ms = int((time.monotonic() - retrieval_started) * 1000)

            contexts = format_contexts(results)

            entry["_full_contexts"] = contexts

            entry["contexts"] = [
                {
                    "chunk_id": item["chunk_id"],
                    "document_id": item["document_id"],
                    "document_title": item["document_title"],
                    "chunk_index": item["chunk_index"],
                    "score": round(float(item.get("score", 0.0)), 4),
                    "rerank_score": (
                        round(float(item["rerank_score"]), 4)
                        if "rerank_score" in item
                        else None
                    ),
                    "preview": (item.get("content") or "")[:240],
                }
                for item in results
            ]

            if not results:
                entry["error"] = "No documents were retrieved for this question."
                entry["latency_ms"] = {
                    "retrieval": retrieval_ms,
                    "generation": 0,
                    "scoring": 0,
                    "total": retrieval_ms,
                }
                return entry

            generation_started = time.monotonic()
            answer = self._answer(build_rag_prompt(sample.question, results))
            generation_ms = int(
                (time.monotonic() - generation_started) * 1000
            )

            entry["answer"] = answer

            scoring_started = time.monotonic()

            results_by_metric = score_sample(
                sample,
                answer,
                contexts,
                metrics=metrics,
                judge=judge,
                embedder=self._embed,
                llm_decomposition=self.config.llm_decomposition,
            )

            entry["scores"] = {
                name: result.to_dict()
                for name, result in results_by_metric.items()
            }

            scoring_ms = int((time.monotonic() - scoring_started) * 1000)

            entry["latency_ms"] = {
                "retrieval": retrieval_ms,
                "generation": generation_ms,
                "scoring": scoring_ms,
                "total": int((time.monotonic() - started) * 1000),
            }

        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
            entry["latency_ms"] = {
                "total": int((time.monotonic() - started) * 1000),
            }
            self._log(
                "warning",
                "Sample %s failed during evaluation: %s",
                sample.id,
                exc,
            )

        return entry
