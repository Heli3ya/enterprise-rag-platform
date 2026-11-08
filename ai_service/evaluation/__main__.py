"""
Command line entry point.

Run the evaluation inside the AI service container::

    docker compose exec ai_service python -m evaluation \\
        --tenant-id 1 --department-ids 1 --limit 10

Or validate the dataset without spending any LLM time::

    docker compose exec ai_service python -m evaluation --list-dataset

Exit codes
----------
``0``  the run completed and every configured threshold was met
``1``  the run failed (bad scope, missing dataset, unreachable LLM)
``2``  invalid arguments
``3``  the run completed but at least one metric is below its threshold
"""

import argparse
import json
import sys

from .config import EvalConfig
from .dataset import DatasetError, dataset_summary, load_dataset
from .jobs import build_request
from .runner import EvaluationRunner, RunError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description="Score the RAG pipeline against the ground-truth dataset.",
    )

    parser.add_argument("--tenant-id", type=int)
    parser.add_argument(
        "--department-ids",
        help="Comma separated department ids (default: AI_EVAL_DEPARTMENT_IDS).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Evaluate only the first N samples.",
    )
    parser.add_argument(
        "--sample-ids",
        help="Comma separated sample ids to evaluate.",
    )
    parser.add_argument(
        "--metrics",
        help=(
            "Comma separated metrics. Available: faithfulness, "
            "answer_relevancy, context_precision, answer_correctness."
        ),
    )
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--dataset", help="Path to the JSONL dataset.")
    parser.add_argument("--output-dir", help="Directory for the reports.")
    parser.add_argument(
        "--list-dataset",
        action="store_true",
        help="Print a dataset summary and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and dataset without calling the LLM.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full report as JSON instead of a summary table.",
    )

    return parser


def build_runner(config):
    """Wire the runner to the already-loaded models and DB pool."""

    from db import get_db_connection, release_db_connection
    from main import (
        ENABLE_RERANKER,
        encode_query_cached,
        inference_lock,
        llm_client,
        models,
    )

    if not models.wait_until_ready():
        print(
            "[evaluation] the models are still loading; try again shortly.",
            file=sys.stderr,
        )

    def embed(texts):
        model = models.get_embedding_model()

        with inference_lock:
            vectors = model.encode(
                texts,
                batch_size=8,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

        return vectors.tolist()

    reranker = None

    if ENABLE_RERANKER:
        def _rerank(query, texts):
            model = models.get_reranker_model()

            with inference_lock:
                scores = model.predict(
                    [[query, text] for text in texts],
                    show_progress_bar=False,
                )

            return [float(score) for score in scores]

        reranker = _rerank

    return EvaluationRunner(
        config,
        llm_client=llm_client,
        embedder=embed,
        embed_query=encode_query_cached,
        reranker=reranker,
        connection_factory=get_db_connection,
        connection_releaser=release_db_connection,
    )


def _print_summary(report):
    metrics = report["config"]["metrics"]
    summary = report["summary"]

    print("")
    print(f"run        : {report['run_id']}")
    print(f"backend    : {report['backend']} ({report.get('backend_note') or 'ok'})")
    print(f"samples    : {report['dataset']['samples']}")
    print(f"duration   : {report['duration_seconds']}s")
    print("")

    header = f"{'metric':<20}{'mean':>8}{'median':>9}{'min':>8}{'max':>8}{'n':>6}"
    print(header)
    print("-" * len(header))

    for metric in metrics:
        entry = summary.get(metric) or {}

        def fmt(value):
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{metric:<20}"
            f"{fmt(entry.get('mean')):>8}"
            f"{fmt(entry.get('median')):>9}"
            f"{fmt(entry.get('min')):>8}"
            f"{fmt(entry.get('max')):>8}"
            f"{entry.get('count', 0):>6}"
        )

    passed = summary.get("passed")

    if passed is not None:
        print("")
        print(
            f"thresholds : {summary['checks_passed']}/"
            f"{summary['checks_run']} passed"
            f" -> {'PASS' if passed else 'FAIL'}"
        )

    errors = [
        sample["id"] for sample in report["samples"] if sample.get("error")
    ]

    if errors:
        print(f"failed samples ({len(errors)}): {', '.join(errors[:10])}")

    paths = report.get("report_paths") or {}

    if paths:
        print("")
        print(f"report     : {paths.get('json')}")
        print(f"csv        : {paths.get('csv')}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    config = EvalConfig.from_env()

    overrides = {}

    if args.dataset:
        overrides["dataset_path"] = args.dataset

    if args.output_dir:
        overrides["output_dir"] = args.output_dir

    if overrides:
        from pathlib import Path

        overrides = {
            key: Path(value) for key, value in overrides.items()
        }
        config = config.with_overrides(**overrides)

    if args.list_dataset:
        try:
            samples = load_dataset(config.dataset_path)
        except DatasetError as exc:
            print(f"[evaluation] {exc}", file=sys.stderr)
            return 1

        print(json.dumps(dataset_summary(samples), indent=2))
        return 0

    department_ids = ()

    if args.department_ids:
        try:
            department_ids = tuple(
                int(part)
                for part in args.department_ids.split(",")
                if part.strip()
            )
        except ValueError:
            print(
                "[evaluation] --department-ids must be comma separated integers.",
                file=sys.stderr,
            )
            return 2

    metrics = ()

    if args.metrics:
        metrics = tuple(
            part.strip() for part in args.metrics.split(",") if part.strip()
        )

    request = build_request(
        {
            "tenant_id": args.tenant_id,
            "department_ids": department_ids,
            "limit": args.limit,
            "sample_ids": (
                tuple(part.strip() for part in args.sample_ids.split(","))
                if args.sample_ids
                else ()
            ),
            "metrics": metrics,
            "top_k": args.top_k,
        }
    )

    if args.dry_run:
        scope = request.resolve(config)

        try:
            samples = load_dataset(scope["dataset_path"])
        except DatasetError as exc:
            print(f"[evaluation] {exc}", file=sys.stderr)
            return 1

        print(
            json.dumps(
                {
                    "tenant_id": scope["tenant_id"],
                    "department_ids": list(scope["department_ids"]),
                    "metrics": list(scope["metrics"]),
                    "limit": scope["limit"],
                    "top_k": scope["top_k"],
                    "dataset": dataset_summary(samples),
                },
                indent=2,
            )
        )

        if scope["tenant_id"] is None or not scope["department_ids"]:
            print(
                "[evaluation] missing tenant/department scope.",
                file=sys.stderr,
            )
            return 2

        return 0

    try:
        runner = build_runner(config)
        report = runner.run(request)
    except (DatasetError, RunError) as exc:
        print(f"[evaluation] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - runtime failures
        print(f"[evaluation] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)

    if report["summary"].get("passed") is False:
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
