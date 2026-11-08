"""
Unit tests for the RAG evaluation subsystem.

These run without FastAPI and without the transformer models: the judge,
the embedder and the retrieval layer are all injected, which is exactly
why they were written as dependencies in the first place.
"""

import json
import re

import pytest

from evaluation.config import EvalConfig
from evaluation.dataset import (
    DatasetError,
    EvalSample,
    dataset_summary,
    load_dataset,
    select_samples,
)
from evaluation.jobs import EvaluationBusy, JobRegistry, build_request
from evaluation.judge import (
    JudgeError,
    coerce_bool_list,
    coerce_str_list,
    extract_json,
)
from evaluation.metrics import (
    answer_correctness,
    answer_relevancy,
    average_precision,
    context_precision,
    faithfulness,
    score_sample,
    strip_citation_markers,
    token_f1,
)
from evaluation.runner import EvaluationRunner, RunError, RunRequest


# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------


class FakeJudge:
    """Judge with scripted answers, so metric maths is tested in isolation."""

    def __init__(
        self,
        statements=None,
        verdicts=None,
        questions=None,
        context_verdicts=None,
        error=None,
    ):
        self.statements = statements or []
        self.verdicts = verdicts or []
        self.questions = questions or []
        self.context_verdicts = context_verdicts or []
        self.error = error

    def _raise(self):
        if self.error:
            raise JudgeError(self.error)

    def decompose_statements(self, answer):
        self._raise()
        return list(self.statements)

    def verify_statements(self, statements, contexts):
        self._raise()
        return list(self.verdicts)

    def generate_questions(self, answer, count=None):
        self._raise()
        return list(self.questions)

    def judge_context_relevance(self, question, ground_truth, contexts):
        self._raise()
        return list(self.context_verdicts)


class ConstantEmbedder:
    """Every text maps to the same vector, so cosine similarity is 1.0."""

    def __call__(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FixedEmbedder:
    """Deterministic vectors: identical text -> identical vector."""

    def __call__(self, texts):
        vectors = []

        for text in texts:
            seed = sum(ord(char) for char in text) % 97 + 1
            vectors.append(
                [
                    float(seed),
                    float(len(text) % 13 + 1),
                    float(seed % 7 + 1),
                ]
            )

        return vectors


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))

    def fetchall(self):
        return self.connection.rows.pop(0) if self.connection.rows else []


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def cursor(self):
        return FakeCursor(self)


class ScriptedLLM:
    """Routes prompts by their first meaningful instruction."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, answer="The answer.", statements=None, verdicts=None):
        self.answer = answer
        self.statements = statements or ["A statement."]
        self.verdicts = verdicts or [True]
        self.prompts = []

    @staticmethod
    def _requested_count(prompt, fallback):
        match = re.search(r"JSON array of (\d+) booleans", prompt)

        return int(match.group(1)) if match else fallback

    def generate_with_options(self, prompt, **kwargs):
        self.prompts.append(prompt)

        if "Break the ANSWER into short" in prompt:
            return json.dumps(self.statements)

        if "strict fact checker" in prompt:
            count = self._requested_count(prompt, len(self.verdicts))
            return json.dumps([True] * count)

        if "Write 3 short questions" in prompt:
            return json.dumps(["What is the answer?", "How many?", "Where?"])

        if "grading a document retrieval system" in prompt:
            count = self._requested_count(prompt, 1)
            return json.dumps([True] * count)

        return self.answer


@pytest.fixture
def sample_dataset(tmp_path):
    path = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "t-01",
            "question": "How many annual leave days?",
            "ground_truth": "26 working days per year.",
            "reference_contexts": ["Full-time employees accrue 26 working days."],
            "document": "hr.txt",
            "tags": ["hr"],
        },
        {
            "id": "t-02",
            "question": "How often must passwords rotate?",
            "ground_truth": "Every 180 days.",
            "document": "it.txt",
            "tags": ["security"],
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def make_config(tmp_path, dataset_path, **overrides):
    defaults = {
        "dataset_path": dataset_path,
        "output_dir": tmp_path / "reports",
        "metrics": (
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "answer_correctness",
        ),
        "default_tenant_id": 1,
        "default_department_ids": (1,),
        "judge_timeout": 5,
        "keep_reports": 5,
    }
    defaults.update(overrides)
    return EvalConfig(**defaults)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def test_dataset_loads_the_shipped_ground_truth():
    from evaluation.config import DEFAULT_DATASET_PATH

    samples = load_dataset(DEFAULT_DATASET_PATH)

    assert len(samples) >= 50
    assert len({sample.id for sample in samples}) == len(samples)
    assert all(sample.question for sample in samples)
    assert all(sample.ground_truth for sample in samples)
    assert all(sample.reference_contexts for sample in samples)


def test_dataset_summary_lists_documents():
    from evaluation.config import DEFAULT_DATASET_PATH

    summary = dataset_summary(load_dataset(DEFAULT_DATASET_PATH))

    assert summary["document_count"] == 6
    assert "hr-leave-policy.txt" in summary["documents"]
    assert summary["with_reference_contexts"] == summary["samples"]


def test_dataset_rejects_a_missing_field(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x", "question": "Q?"}\n', encoding="utf-8")

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_dataset_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "dup.jsonl"
    row = {"id": "a", "question": "Q?", "ground_truth": "A."}
    path.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_dataset_rejects_invalid_json(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(DatasetError):
        load_dataset(path)


def test_select_samples_filters_by_id(sample_dataset):
    samples = load_dataset(sample_dataset)

    assert [s.id for s in select_samples(samples, sample_ids=["t-02"])] == ["t-02"]
    assert len(select_samples(samples, limit=1)) == 1

    with pytest.raises(DatasetError):
        select_samples(samples, sample_ids=["missing"])


# ---------------------------------------------------------------------------
# Judge parsing
# ---------------------------------------------------------------------------


def test_extract_json_handles_code_fences():
    payload = extract_json('```json\n["a", "b"]\n```', "array")

    assert payload == ["a", "b"]


def test_extract_json_repairs_trailing_commas_and_literals():
    payload = extract_json('[True, False,]', "array")

    assert payload == [True, False]


def test_extract_json_finds_the_array_inside_prose():
    payload = extract_json(
        'Sure, here it is: ["one", "two"] — hope that helps.',
        "array",
    )

    assert payload == ["one", "two"]


def test_extract_json_raises_on_prose_without_json():
    with pytest.raises(JudgeError):
        extract_json("I cannot answer that.", "array")


def test_coerce_bool_list_accepts_loose_answers():
    assert coerce_bool_list(["yes", "no", "true"], 3) == [True, False, True]
    assert coerce_bool_list([1, 0], 2) == [True, False]
    assert coerce_bool_list({"verdicts": [True]}, 1) == [True]


def test_coerce_str_list_unwraps_objects():
    payload = coerce_str_list(
        {"statements": ["a", {"statement": "b"}, ""]},
        limit=5,
    )

    assert payload == ["a", "b"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_average_precision_rewards_early_hits():
    assert average_precision([True, True]) == 1.0
    assert average_precision([True, False, True]) == pytest.approx(0.8333, abs=1e-4)
    assert average_precision([False, False]) == 0.0
    assert average_precision([]) == 0.0


def test_faithfulness_with_judge_counts_supported_statements():
    judge = FakeJudge(
        statements=["a", "b", "c"],
        verdicts=[True, False, True],
    )

    result = faithfulness(
        "answer text",
        ["ctx"],
        judge=judge,
        use_llm_decomposition=True,
    )

    assert result.method == "llm"
    assert result.score == pytest.approx(2 / 3)
    assert result.details["supported"] == 2
    assert result.details["decomposition"] == "llm"


def test_faithfulness_splits_sentences_without_the_judge():
    judge = FakeJudge(verdicts=[True, False, True])

    result = faithfulness(
        "First fact. Second fact. Third fact.",
        ["ctx"],
        judge=judge,
    )

    assert result.method == "llm"
    assert result.details["decomposition"] == "sentence"
    assert result.details["statements"] == 3
    assert result.score == pytest.approx(2 / 3)


def test_faithfulness_rejects_a_mismatched_verdict_count():
    judge = FakeJudge(verdicts=[True])

    result = faithfulness(
        "Alpha is supported. Beta is supported. Gamma is supported.",
        ["ctx"],
        judge=judge,
    )

    # A judge that answers with the wrong number of verdicts is not
    # trusted; the deterministic lexical path takes over.
    assert result.method == "lexical"


def test_split_statements_drops_fragments_without_content_words():
    from evaluation.metrics import split_statements

    statements = split_statements("Yes. The code is ORBIT-742.")

    assert statements == ["The code is ORBIT-742."]


def test_faithfulness_falls_back_to_lexical_when_judge_fails():
    judge = FakeJudge(error="model returned garbage")
    answer = "Documents are retained for seven years."
    contexts = ["Documents are retained for seven years according to policy."]

    result = faithfulness(answer, contexts, judge=judge)

    assert result.method == "lexical"
    assert result.score == 1.0
    assert "fallback_reason" in result.details


def test_lexical_faithfulness_flags_an_invented_number():
    answer = "Documents are retained for 9 years."
    contexts = ["Documents are retained for 7 years."]

    result = faithfulness(answer, contexts)

    assert result.score == 0.0


def test_faithfulness_without_context_is_zero():
    assert faithfulness("Some answer", []).score == 0.0
    assert faithfulness("", ["ctx"]).score == 0.0


def test_answer_relevancy_with_judge():
    judge = FakeJudge(questions=["How many days?", "How many days?"])
    embedder = FixedEmbedder()

    result = answer_relevancy(
        "How many days?",
        "How many days?",
        judge=judge,
        embedder=embedder,
    )

    assert result.method == "llm"
    assert result.score == pytest.approx(1.0, abs=1e-6)


def test_answer_relevancy_falls_back_to_embedding_similarity():
    judge = FakeJudge(error="nope")

    result = answer_relevancy(
        "How many days?",
        "How many days?",
        judge=judge,
        embedder=FixedEmbedder(),
    )

    assert result.method == "embedding"
    assert result.score > 0.9


def test_context_precision_with_judge():
    judge = FakeJudge(context_verdicts=[True, False, True])

    result = context_precision(
        "question",
        "ground truth",
        ["c1", "c2", "c3"],
        judge=judge,
    )

    assert result.method == "llm"
    assert result.score == pytest.approx(0.8333, abs=1e-4)
    assert result.details["relevant_chunks"] == 2


def test_context_precision_without_ground_truth_is_zero():
    result = context_precision("q", "", ["c1"])

    assert result.score == 0.0
    assert result.method == "none"


def test_token_f1():
    assert token_f1("26 working days", "26 working days") == 1.0
    assert token_f1("apples", "oranges") == 0.0
    assert 0.0 < token_f1("26 working days per year", "26 days") < 1.0


def test_answer_correctness_blends_factual_and_semantic():
    embedder = FixedEmbedder()

    result = answer_correctness(
        "26 working days",
        "26 working days",
        embedder=embedder,
    )

    assert result.score == pytest.approx(1.0, abs=1e-6)
    assert result.details["token_f1"] == 1.0


def test_answer_correctness_is_zero_for_an_empty_answer():
    assert answer_correctness("", "reference").score == 0.0


def test_strip_citation_markers():
    assert strip_citation_markers("A fact. [95] Another. [12][13]") == (
        "A fact. Another."
    )
    assert strip_citation_markers("") == ""
    assert strip_citation_markers("No markers here.") == "No markers here."


def test_score_sample_never_shows_citation_markers_to_the_judge():
    seen = {}

    class RecordingJudge(FakeJudge):
        def verify_statements(self, statements, contexts):
            seen["statements"] = list(statements)
            return [True] * len(statements)

    sample = EvalSample(
        id="x",
        question="How many days?",
        ground_truth="26 working days.",
    )

    score_sample(
        sample,
        "Employees receive 26 working days. [95]",
        ["Employees accrue 26 working days."],
        metrics=("faithfulness",),
        judge=RecordingJudge(),
    )

    joined = " ".join(seen["statements"])

    assert "[95]" not in joined
    assert "26 working days" in joined


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_runner_writes_json_and_csv(tmp_path, sample_dataset, monkeypatch):
    import evaluation.runner as runner_module

    def fake_retrieve(connection, query, **kwargs):
        return [
            {
                "chunk_id": 11,
                "content": "Full-time employees accrue 26 working days.",
                "chunk_index": 0,
                "document_id": 1,
                "document_title": "hr.txt",
                "score": 0.9,
                "rerank_score": 0.8,
            }
        ]

    monkeypatch.setattr(runner_module, "retrieve", fake_retrieve)

    config = make_config(tmp_path, sample_dataset)
    runner = EvaluationRunner(
        config,
        llm_client=ScriptedLLM(
            answer="Employees accrue 26 working days. [11]",
            statements=["Employees accrue 26 working days."],
            verdicts=[True],
        ),
        embedder=ConstantEmbedder(),
        embed_query=lambda text: [1.0, 0.0, 0.0],
        connection_factory=lambda: FakeConnection(),
        connection_releaser=lambda connection, discard=False: None,
    )

    report = runner.run(RunRequest(tenant_id=1, department_ids=(1,)))

    assert report["run_id"]
    assert len(report["samples"]) == 2
    assert report["samples"][0]["scores"]["faithfulness"]["score"] == 1.0
    assert report["summary"]["faithfulness"]["mean"] == pytest.approx(1.0)
    assert report["summary"]["passed"] is True

    json_path = tmp_path / "reports" / f"report_{report['run_id']}.json"
    csv_path = tmp_path / "reports" / f"report_{report['run_id']}.csv"

    assert json_path.exists()
    assert csv_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["dataset"]["samples"] == 2

    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert "faithfulness" in header
    assert "answer_relevancy" in header


def test_runner_records_a_failed_sample(tmp_path, sample_dataset, monkeypatch):
    import evaluation.runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "retrieve",
        lambda connection, query, **kwargs: [],
    )

    config = make_config(tmp_path, sample_dataset)
    runner = EvaluationRunner(
        config,
        llm_client=ScriptedLLM(),
        embedder=FixedEmbedder(),
        embed_query=lambda text: FixedEmbedder()([text])[0],
        connection_factory=lambda: FakeConnection(),
        connection_releaser=lambda connection, discard=False: None,
    )

    report = runner.run(RunRequest(tenant_id=1, department_ids=(1,)))

    assert report["samples"][0]["error"]
    assert report["summary"]["faithfulness"]["count"] == 0


def test_runner_requires_a_tenant_scope(tmp_path, sample_dataset):
    config = make_config(
        tmp_path,
        sample_dataset,
        default_tenant_id=None,
    )
    runner = EvaluationRunner(config, llm_client=ScriptedLLM())

    with pytest.raises(RunError):
        runner.run(RunRequest())


def test_runner_requires_departments(tmp_path, sample_dataset):
    config = make_config(
        tmp_path,
        sample_dataset,
        default_department_ids=(),
    )
    runner = EvaluationRunner(config, llm_client=ScriptedLLM())

    with pytest.raises(RunError):
        runner.run(RunRequest(tenant_id=1))


def test_runner_prunes_old_reports(tmp_path, sample_dataset, monkeypatch):
    import evaluation.runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "retrieve",
        lambda connection, query, **kwargs: [],
    )

    config = make_config(tmp_path, sample_dataset, keep_reports=1)
    output_dir = tmp_path / "reports"
    output_dir.mkdir()

    for index in range(3):
        (output_dir / f"report_old{index}.json").write_text("{}", encoding="utf-8")
        (output_dir / f"report_old{index}.csv").write_text("", encoding="utf-8")

    runner = EvaluationRunner(
        config,
        llm_client=ScriptedLLM(),
        embedder=FixedEmbedder(),
        embed_query=lambda text: FixedEmbedder()([text])[0],
        connection_factory=lambda: FakeConnection(),
        connection_releaser=lambda connection, discard=False: None,
    )

    runner.run(RunRequest(tenant_id=1, department_ids=(1,)))

    remaining = sorted(path.name for path in output_dir.glob("report_*.json"))
    assert len(remaining) == 1


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def test_build_request_parses_payload():
    request = build_request(
        {
            "tenant_id": 3,
            "department_ids": [1, 2],
            "limit": 5,
            "metrics": "faithfulness, answer_relevancy",
        }
    )

    assert request.tenant_id == 3
    assert request.department_ids == (1, 2)
    assert request.limit == 5
    assert request.metrics == ("faithfulness", "answer_relevancy")


def test_build_request_rejects_a_bad_limit():
    with pytest.raises(ValueError):
        build_request({"limit": 0})


def test_job_registry_completes_a_run(sample_dataset, tmp_path, monkeypatch):
    import evaluation.runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "retrieve",
        lambda connection, query, **kwargs: [],
    )

    registry = JobRegistry()
    runner = EvaluationRunner(
        make_config(tmp_path, sample_dataset),
        llm_client=ScriptedLLM(),
        embedder=FixedEmbedder(),
        embed_query=lambda text: FixedEmbedder()([text])[0],
        connection_factory=lambda: FakeConnection(),
        connection_releaser=lambda connection, discard=False: None,
    )

    job = registry.start(runner, RunRequest(tenant_id=1, department_ids=(1,)))
    assert job["status"] in {"queued", "running"}

    for _ in range(200):
        current = registry.get(job["job_id"])

        if current["status"] in {"succeeded", "failed"}:
            break

        pytest.importorskip("time").sleep(0.02)

    final = registry.get(job["job_id"])

    assert final["status"] == "succeeded"
    assert final["report_paths"]["json"].endswith(".json")
    assert final["summary"]["passed"] is not None
    assert registry.is_running is False


def test_job_registry_rejects_a_second_concurrent_run(sample_dataset, tmp_path):
    registry = JobRegistry()

    class SlowRunner:
        def run(self, request, progress=None):
            import time

            time.sleep(0.3)
            return {"summary": {}, "samples": [], "report_paths": {}}

    registry.start(SlowRunner(), RunRequest())

    with pytest.raises(EvaluationBusy):
        registry.start(SlowRunner(), RunRequest())
