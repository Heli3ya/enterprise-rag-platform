"""
Optional adapter for the real RAGAS library.

The default backend is :mod:`evaluation.metrics`, which implements the
same metric definitions with the service's own LLM client. This adapter
exists for deployments that prefer the upstream implementation.

It is intentionally *optional* and fully guarded:

* ``ragas`` is not in ``requirements.txt`` because it pulls in
  ``datasets``, ``langchain`` and ``pandas`` (hundreds of megabytes) and
  the inference image must stay small.
* nothing here is imported unless ``AI_EVAL_BACKEND=ragas``.
* if the import or the evaluation fails for any reason, the runner keeps
  the internal scores and records the failure in the report.

To enable it::

    pip install "ragas>=0.2" langchain-ollama
    AI_EVAL_BACKEND=ragas

The report schema does not change, so dashboards and the acceptance
criteria are unaffected by the switch.
"""

import logging


logger = logging.getLogger(__name__)

METRIC_ALIASES = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "context_precision": "context_precision",
    "answer_correctness": "answer_correctness",
}


class RagasUnavailable(RuntimeError):
    """The ragas library or one of its wrappers is not installed."""


def is_available():
    try:
        import ragas  # noqa: F401
    except Exception:
        return False

    return True


def _import_ragas():
    try:
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
    except Exception as exc:  # pragma: no cover - depends on install
        raise RagasUnavailable(
            "ragas is not installed or has an incompatible version."
        ) from exc

    return evaluate, EvaluationDataset, SingleTurnSample


def _build_metric_objects(names):
    try:
        from ragas import metrics as ragas_metrics
    except Exception as exc:  # pragma: no cover - depends on install
        raise RagasUnavailable("ragas.metrics could not be imported.") from exc

    objects = []
    skipped = []

    for name in names:
        alias = METRIC_ALIASES.get(name)

        if alias is None:
            continue

        metric = getattr(ragas_metrics, alias, None)

        if metric is None:
            skipped.append(name)
            continue

        objects.append(metric)

    if skipped:
        logger.warning(
            "ragas does not expose these metrics in this version: %s",
            ", ".join(skipped),
        )

    return objects


def _build_llm(llm_client, timeout):
    """
    Wrap the configured provider as a ragas-compatible judge.

    Only Ollama and OpenAI-compatible endpoints are supported, matching
    the two providers the service already speaks.
    """

    try:
        from ragas.llms import LangchainLLMWrapper
    except Exception as exc:  # pragma: no cover - depends on install
        raise RagasUnavailable(
            "ragas.llms could not be imported."
        ) from exc

    provider = getattr(llm_client, "provider", "ollama")
    model = getattr(llm_client, "model", "")
    base_url = getattr(llm_client, "base_url", "")

    try:
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            chat = ChatOllama(
                model=model,
                base_url=base_url.replace("/api", ""),
                temperature=0,
            )
        else:
            from langchain_openai import ChatOpenAI

            chat = ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key=getattr(llm_client, "api_key", "") or "not-needed",
                temperature=0,
                timeout=timeout,
            )
    except Exception as exc:  # pragma: no cover - depends on install
        raise RagasUnavailable(
            f"A LangChain chat model for {provider} is not installed: {exc}"
        ) from exc

    return LangchainLLMWrapper(chat)


def _build_embeddings(embedder):
    """Expose the local embedding model to ragas without a new download."""

    try:
        from ragas.embeddings import BaseRagasEmbeddings
    except Exception as exc:  # pragma: no cover - depends on install
        raise RagasUnavailable(
            "ragas.embeddings could not be imported."
        ) from exc

    class CallableEmbeddings(BaseRagasEmbeddings):
        """Adapter that reuses the service's already-loaded model."""

        def embed_query(self, text):
            return embedder([text])[0]

        def embed_documents(self, texts):
            return embedder(list(texts))

        async def aembed_query(self, text):
            return self.embed_query(text)

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

    return CallableEmbeddings()


def evaluate_batch(
    rows,
    *,
    metrics,
    llm_client,
    embedder,
    timeout=180,
):
    """
    Score a batch of evaluated samples with the upstream implementation.

    ``rows`` is a list of dicts with ``question``, ``answer``,
    ``contexts`` and ``ground_truth``. Returns a dict of
    ``{sample_index: {metric: score}}``.
    """

    evaluate, EvaluationDataset, SingleTurnSample = _import_ragas()

    metric_objects = _build_metric_objects(metrics)

    if not metric_objects:
        raise RagasUnavailable("No requested metric exists in this ragas build.")

    samples = []
    usable_indexes = []

    for index, row in enumerate(rows):
        if not row.get("answer") or not row.get("contexts"):
            continue

        samples.append(
            SingleTurnSample(
                user_input=row["question"],
                response=row["answer"],
                retrieved_contexts=list(row["contexts"]),
                reference=row.get("ground_truth") or "",
            )
        )
        usable_indexes.append(index)

    if not samples:
        return {}

    dataset = EvaluationDataset(samples=samples)

    result = evaluate(
        dataset,
        metrics=metric_objects,
        llm=_build_llm(llm_client, timeout),
        embeddings=_build_embeddings(embedder),
        raise_exceptions=False,
        show_progress=False,
    )

    frame = result.to_pandas()
    scores = {}

    for position, row_index in enumerate(usable_indexes):
        row_scores = {}

        for metric in metrics:
            if metric not in frame.columns:
                continue

            value = frame.iloc[position][metric]

            try:
                row_scores[metric] = float(value)
            except (TypeError, ValueError):
                continue

        scores[row_index] = row_scores

    return scores
