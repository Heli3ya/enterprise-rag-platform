"""
RAGAS-equivalent metrics.

The four metrics implemented here follow the definitions used by the
RAGAS project:

``faithfulness``
    The answer is decomposed into atomic statements and every statement
    is checked against the retrieved context. Score = supported /
    total statements. This is the primary hallucination signal.

``answer_relevancy``
    ``N`` questions are generated from the answer, embedded, and
    compared with the original question by cosine similarity. Score =
    mean similarity. A vague or off-topic answer produces unrelated
    questions and therefore a low score.

``context_precision``
    Every retrieved chunk is graded as useful or not for reaching the
    reference answer, then averaged as mean average precision so that
    relevant chunks ranked early are rewarded.

``answer_correctness``
    Reference-based accuracy: a weighted blend of token F1 against the
    ground truth (0.75) and embedding similarity (0.25), mirroring the
    RAGAS weighting.

Each metric degrades gracefully: if the language model cannot be used
as a judge, a deterministic lexical implementation runs instead and the
result is tagged with ``method`` so the report never hides a degraded
run.
"""

import math
import re
from dataclasses import dataclass, field


# Words that carry no factual content. Keeping this list small matters:
# over-filtering hides real numbers and names.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so",
    "of", "in", "on", "at", "to", "for", "from", "by", "with", "without",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "doing", "done",
    "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might",
    "must", "need", "needs", "needed",
    "i", "you", "he", "she", "it", "we", "they", "them", "their", "our",
    "your", "my", "his", "her", "its", "this", "that", "these", "those",
    "there", "here", "as", "also", "not", "no", "yes", "any", "all",
    "each", "every", "some", "such", "very", "more", "most", "much",
    "per", "into", "about", "over", "under", "up", "down", "out",
    "what", "which", "who", "whom", "whose", "when", "where", "why",
    "how", "many", "may", "one", "two", "according", "document",
}

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%/+-]*")

# `[12]` is a citation marker, not a factual claim. Feeding it to the
# judge makes small models invent statements such as "the information
# comes from [12]" and then mark them unsupported, which drags
# faithfulness down for a perfectly good answer.
CITATION_MARKER_PATTERN = re.compile(r"\[\d+\]")


def strip_citation_markers(text):
    """Remove inline citation markers before any metric sees the text."""

    if not text:
        return ""

    cleaned = CITATION_MARKER_PATTERN.sub(" ", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip()


SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")


def split_statements(answer, max_statements=8):
    """
    Split an answer into statements without asking the model.

    Asking a small local model to decompose an answer produces eight
    restatements of the same sentence, and the model then contradicts
    itself on half of them. Splitting on sentence boundaries is
    deterministic, free, and for answers of one to five sentences it is
    at least as accurate. LLM decomposition stays available through
    ``use_llm_decomposition`` for deployments with a strong judge.
    """

    text = strip_citation_markers(answer)

    if not text:
        return []

    statements = []

    for part in SENTENCE_SPLIT_PATTERN.split(text):
        statement = part.strip()

        if not statement:
            continue

        # A fragment with no content words ("OK.", "1.") is not a claim.
        if not token_set(statement):
            continue

        statements.append(statement)

    return statements[:max_statements]

# A statement is considered lexically supported when this share of its
# content words appears in the retrieved context.
LEXICAL_SUPPORT_THRESHOLD = 0.60

# A context is considered lexically relevant to the ground truth above
# this share of covered content words.
LEXICAL_RELEVANCE_THRESHOLD = 0.35


def tokenize(text):
    """Lowercase content words, numbers preserved."""

    if not text:
        return []

    tokens = []

    for raw in TOKEN_PATTERN.findall(text.lower()):
        token = raw.strip("._%/+-")

        if not token or token in STOPWORDS:
            continue

        tokens.append(token)

    return tokens


def token_set(text):
    return set(tokenize(text))


def numbers_in(text):
    return {token for token in tokenize(text) if any(c.isdigit() for c in token)}


def coverage(needle_tokens, haystack_tokens):
    """Share of ``needle_tokens`` present in ``haystack_tokens``."""

    if not needle_tokens:
        return 0.0

    return len(needle_tokens & haystack_tokens) / len(needle_tokens)


def token_f1(prediction, reference):
    """Bag-of-words F1, a cheap proxy for factual overlap."""

    predicted = tokenize(prediction)
    expected = tokenize(reference)

    if not predicted and not expected:
        return 1.0

    if not predicted or not expected:
        return 0.0

    predicted_counts = {}
    expected_counts = {}

    for token in predicted:
        predicted_counts[token] = predicted_counts.get(token, 0) + 1

    for token in expected:
        expected_counts[token] = expected_counts.get(token, 0) + 1

    overlap = sum(
        min(count, expected_counts.get(token, 0))
        for token, count in predicted_counts.items()
    )

    if overlap == 0:
        return 0.0

    precision = overlap / len(predicted)
    recall = overlap / len(expected)

    return 2 * precision * recall / (precision + recall)


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0

    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b

    if left_norm <= 0 or right_norm <= 0:
        return 0.0

    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def clamp(value, low=0.0, high=1.0):
    if value is None or not math.isfinite(value):
        return low

    return max(low, min(high, float(value)))


def average_precision(relevance):
    """
    Mean average precision over a ranked relevance list.

    Mirrors RAGAS ``context_precision``: the sum of precision@k for the
    relevant positions, divided by the number of relevant chunks.
    """

    if not relevance:
        return 0.0

    relevant_total = sum(1 for flag in relevance if flag)

    if relevant_total == 0:
        return 0.0

    hits = 0
    accumulated = 0.0

    for index, flag in enumerate(relevance, start=1):
        if not flag:
            continue

        hits += 1
        accumulated += hits / index

    return accumulated / relevant_total


@dataclass
class MetricResult:
    name: str
    score: float
    method: str = "llm"
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "score": round(self.score, 4),
            "method": self.method,
            **self.details,
        }


# ---------------------------------------------------------------------------
# Faithfulness
# ---------------------------------------------------------------------------


def _lexical_faithfulness(answer, contexts):
    context_tokens = set()
    context_numbers = set()

    for context in contexts:
        context_tokens |= token_set(context)
        context_numbers |= numbers_in(context)

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", answer)
        if part.strip()
    ]

    if not sentences:
        return MetricResult(
            name="faithfulness",
            score=0.0,
            method="lexical",
            details={"statements": 0, "supported": 0},
        )

    supported = 0
    verdicts = []

    for sentence in sentences:
        tokens = token_set(sentence)

        if not tokens:
            continue

        score = coverage(tokens, context_tokens)

        # A number that appears nowhere in the context is a strong
        # hallucination signal, regardless of the surrounding wording.
        sentence_numbers = numbers_in(sentence)
        number_ok = sentence_numbers <= context_numbers if sentence_numbers else True

        verdict = score >= LEXICAL_SUPPORT_THRESHOLD and number_ok

        verdicts.append(
            {
                "statement": sentence[:240],
                "coverage": round(score, 3),
                "supported": verdict,
            }
        )

        if verdict:
            supported += 1

    total = len(verdicts)

    return MetricResult(
        name="faithfulness",
        score=(supported / total) if total else 0.0,
        method="lexical",
        details={"statements": total, "supported": supported, "verdicts": verdicts},
    )


def faithfulness(
    answer,
    contexts,
    judge=None,
    use_llm_decomposition=False,
):
    """Share of answer statements that the retrieved context supports."""

    if not answer or not answer.strip():
        return MetricResult(
            name="faithfulness",
            score=0.0,
            method="none",
            details={"reason": "empty answer"},
        )

    if not contexts:
        return MetricResult(
            name="faithfulness",
            score=0.0,
            method="none",
            details={"reason": "no retrieved context"},
        )

    if judge is not None:
        try:
            if use_llm_decomposition:
                statements = judge.decompose_statements(answer)
                decomposition = "llm"
            else:
                statements = split_statements(answer)
                decomposition = "sentence"

            if not statements:
                return MetricResult(
                    name="faithfulness",
                    score=0.0,
                    method="llm",
                    details={
                        "statements": 0,
                        "supported": 0,
                        "decomposition": decomposition,
                    },
                )

            verdicts = judge.verify_statements(statements, contexts)

            if len(verdicts) != len(statements):
                raise ValueError(
                    "The judge returned "
                    f"{len(verdicts)} verdicts for {len(statements)} statements."
                )

            supported = sum(1 for flag in verdicts if flag)

            return MetricResult(
                name="faithfulness",
                score=supported / len(statements),
                method="llm",
                details={
                    "statements": len(statements),
                    "supported": supported,
                    "decomposition": decomposition,
                    "verdicts": [
                        {"statement": statement, "supported": flag}
                        for statement, flag in zip(statements, verdicts)
                    ],
                },
            )

        except Exception as exc:
            fallback = _lexical_faithfulness(answer, contexts)
            fallback.details["fallback_reason"] = str(exc)[:300]
            return fallback

    return _lexical_faithfulness(answer, contexts)


# ---------------------------------------------------------------------------
# Answer relevancy
# ---------------------------------------------------------------------------


def _embedding_relevancy(question, answer, embedder, reason=""):
    try:
        vectors = embedder([question, answer])
        score = clamp(cosine_similarity(vectors[0], vectors[1]))
        method = "embedding"
    except Exception as exc:  # pragma: no cover - defensive
        question_tokens = token_set(question)
        answer_tokens = token_set(answer)
        score = clamp(coverage(question_tokens, answer_tokens))
        method = "lexical"
        reason = f"{reason} embedding failed: {exc}"[:300]

    details = {}

    if reason:
        details["fallback_reason"] = reason

    return MetricResult(
        name="answer_relevancy",
        score=score,
        method=method,
        details=details,
    )


def answer_relevancy(question, answer, judge=None, embedder=None):
    """
    Mean cosine similarity between the question and questions that the
    answer implies.
    """

    if not answer or not answer.strip():
        return MetricResult(
            name="answer_relevancy",
            score=0.0,
            method="none",
            details={"reason": "empty answer"},
        )

    if judge is None or embedder is None:
        if embedder is None:
            return MetricResult(
                name="answer_relevancy",
                score=0.0,
                method="none",
                details={"reason": "no embedder"},
            )

        return _embedding_relevancy(question, answer, embedder)

    try:
        generated = judge.generate_questions(answer)

        if not generated:
            return _embedding_relevancy(
                question,
                answer,
                embedder,
                reason="the judge generated no questions",
            )

        vectors = embedder([question] + generated)
        question_vector = vectors[0]
        similarities = [
            clamp(cosine_similarity(question_vector, vector))
            for vector in vectors[1:]
        ]

        return MetricResult(
            name="answer_relevancy",
            score=sum(similarities) / len(similarities),
            method="llm",
            details={
                "generated_questions": generated,
                "similarities": [round(value, 4) for value in similarities],
            },
        )

    except Exception as exc:
        return _embedding_relevancy(
            question,
            answer,
            embedder,
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Context precision
# ---------------------------------------------------------------------------


def _lexical_context_precision(question, ground_truth, contexts):
    reference_tokens = token_set(ground_truth) | token_set(question)
    relevance = []

    for context in contexts:
        score = coverage(reference_tokens, token_set(context))
        relevance.append(score >= LEXICAL_RELEVANCE_THRESHOLD)

    return MetricResult(
        name="context_precision",
        score=average_precision(relevance),
        method="lexical",
        details={
            "relevance": relevance,
            "relevant_chunks": sum(1 for flag in relevance if flag),
        },
    )


def context_precision(question, ground_truth, contexts, judge=None):
    """Mean average precision of the retrieved chunks."""

    if not contexts:
        return MetricResult(
            name="context_precision",
            score=0.0,
            method="none",
            details={"reason": "no retrieved context"},
        )

    if not ground_truth or not ground_truth.strip():
        return MetricResult(
            name="context_precision",
            score=0.0,
            method="none",
            details={"reason": "no ground truth"},
        )

    if judge is not None:
        try:
            relevance = judge.judge_context_relevance(
                question,
                ground_truth,
                contexts,
            )

            return MetricResult(
                name="context_precision",
                score=average_precision(relevance),
                method="llm",
                details={
                    "relevance": relevance,
                    "relevant_chunks": sum(1 for flag in relevance if flag),
                },
            )

        except Exception as exc:
            fallback = _lexical_context_precision(
                question,
                ground_truth,
                contexts,
            )
            fallback.details["fallback_reason"] = str(exc)[:300]
            return fallback

    return _lexical_context_precision(question, ground_truth, contexts)


# ---------------------------------------------------------------------------
# Answer correctness
# ---------------------------------------------------------------------------

FACTUAL_WEIGHT = 0.75
SEMANTIC_WEIGHT = 0.25


def answer_correctness(answer, ground_truth, embedder=None):
    """
    Reference-based accuracy.

    RAGAS blends factual overlap (0.75) with semantic similarity (0.25);
    the factual component here is token F1 instead of an LLM claim
    comparison, which keeps the metric deterministic and cheap.
    """

    if not answer or not answer.strip():
        return MetricResult(
            name="answer_correctness",
            score=0.0,
            method="none",
            details={"reason": "empty answer"},
        )

    if not ground_truth or not ground_truth.strip():
        return MetricResult(
            name="answer_correctness",
            score=0.0,
            method="none",
            details={"reason": "no ground truth"},
        )

    factual = token_f1(answer, ground_truth)
    semantic = 0.0
    method = "lexical"

    if embedder is not None:
        try:
            vectors = embedder([answer, ground_truth])
            semantic = clamp(cosine_similarity(vectors[0], vectors[1]))
            method = "mixed"
        except Exception:  # pragma: no cover - defensive
            semantic = 0.0

    score = FACTUAL_WEIGHT * factual + SEMANTIC_WEIGHT * semantic

    return MetricResult(
        name="answer_correctness",
        score=clamp(score),
        method=method,
        details={
            "token_f1": round(factual, 4),
            "semantic_similarity": round(semantic, 4),
        },
    )


METRIC_FUNCTIONS = {
    "faithfulness": faithfulness,
    "answer_relevancy": answer_relevancy,
    "context_precision": context_precision,
    "answer_correctness": answer_correctness,
}


def score_sample(
    sample,
    answer,
    contexts,
    *,
    metrics,
    judge=None,
    embedder=None,
    llm_decomposition=False,
):
    """Compute every requested metric for a single evaluated sample."""

    # Citation markers are stripped once, so no metric can mistake
    # metadata for a claim.
    clean_answer = strip_citation_markers(answer)

    results = {}

    for metric in metrics:
        if metric == "faithfulness":
            results[metric] = faithfulness(
                clean_answer,
                contexts,
                judge=judge,
                use_llm_decomposition=llm_decomposition,
            )
        elif metric == "answer_relevancy":
            results[metric] = answer_relevancy(
                sample.question,
                clean_answer,
                judge=judge,
                embedder=embedder,
            )
        elif metric == "context_precision":
            results[metric] = context_precision(
                sample.question,
                sample.ground_truth,
                contexts,
                judge=judge,
            )
        elif metric == "answer_correctness":
            results[metric] = answer_correctness(
                clean_answer,
                sample.ground_truth,
                embedder=embedder,
            )

    return results
