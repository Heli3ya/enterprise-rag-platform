"""
The relevance floor: the difference between "no match" and "the least
irrelevant chunk".

Fusion normalizes per query, so the best result of every query scores
1.0. That is right for ranking and wrong for deciding whether to answer:
with no absolute signal, a question that nothing in the corpus answers
still produces a citation, and the model writes an answer around it.
These tests pin the absolute floor and the user-visible consequence —
`no_match` instead of a confident answer from an unrelated document.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from api.services import (
    AIServiceError,
    NO_DOCUMENTS_MESSAGE,
    NO_MATCHING_CHUNKS,
    generate_rag_answer,
    generate_rag_stream,
    hybrid_search,
)
from tests.factories import UserFactory


def semantic_hit(chunk_id, content, distance=0.22):
    return SimpleNamespace(
        chunk_id=chunk_id,
        distance=distance,
        chunk=SimpleNamespace(content=content),
    )


def rerank_to(score):
    """A reranker that gives every candidate the same score."""

    def _rerank(query, results):
        return [
            {**item, "rerank_score": score}
            for item in results
        ]

    return _rerank


def search_with(user, semantic_results, rerank_score=None, rerank_error=False):
    patches = [
        patch(
            "api.services.semantic_search",
            return_value=semantic_results,
        ),
        patch("api.services.keyword_search", return_value=[]),
    ]

    if rerank_error:
        patches.append(
            patch(
                "api.services.rerank_results",
                side_effect=AIServiceError("reranker disabled"),
            )
        )
    else:
        patches.append(
            patch(
                "api.services.rerank_results",
                side_effect=rerank_to(rerank_score),
            )
        )

    for item in patches:
        item.start()

    try:
        return hybrid_search("what is the travel policy", user=user)
    finally:
        for item in patches:
            item.stop()


@pytest.mark.django_db
def test_an_irrelevant_candidate_is_dropped():
    user = UserFactory()

    results = search_with(
        user,
        [semantic_hit(1, "SELECT firstname, lastname FROM HR.Employees")],
        rerank_score=-7.2,
    )

    assert results == []


@pytest.mark.django_db
def test_a_relevant_candidate_survives():
    user = UserFactory()

    results = search_with(
        user,
        [semantic_hit(1, "Receipts must be submitted within 30 days.")],
        rerank_score=1.1,
    )

    assert len(results) == 1
    assert results[0]["chunk_id"] == 1


@pytest.mark.django_db
def test_the_floor_is_configurable(monkeypatch):
    user = UserFactory()
    monkeypatch.setattr("api.services.RAG_MIN_RERANK_SCORE", 5.0)

    results = search_with(
        user,
        [semantic_hit(1, "Receipts must be submitted within 30 days.")],
        rerank_score=1.1,
    )

    # A deployment that wants only strong matches can raise the floor
    # without touching code.
    assert results == []


@pytest.mark.django_db
def test_a_candidate_the_reranker_did_not_score_is_dropped():
    user = UserFactory()

    with (
        patch(
            "api.services.semantic_search",
            return_value=[semantic_hit(1, "unrelated text")],
        ),
        patch("api.services.keyword_search", return_value=[]),
        patch(
            "api.services.rerank_results",
            side_effect=lambda query, results: [
                {**item, "rerank_score": -1e9}
                for item in results
            ],
        ),
    ):
        results = hybrid_search("what is the travel policy", user=user)

    # Previously such a row sorted last but still reached the prompt.
    assert results == []


@pytest.mark.django_db
def test_without_the_reranker_the_default_keeps_everything():
    user = UserFactory()

    results = search_with(
        user,
        [semantic_hit(1, "Receipts must be submitted within 30 days.")],
        rerank_error=True,
    )

    # The semantic floor defaults to 0.0: compressed e5 cosines make a
    # real floor lossy, so the previous behaviour is preserved.
    assert len(results) == 1
    assert "rerank_score" in results[0]


@pytest.mark.django_db
def test_without_the_reranker_a_raised_semantic_floor_applies(monkeypatch):
    user = UserFactory()
    monkeypatch.setattr(
        "api.services.RAG_MIN_SEMANTIC_SIMILARITY",
        0.85,
    )

    results = search_with(
        user,
        [
            semantic_hit(
                1,
                "SELECT firstname FROM HR.Employees",
                distance=0.28,
            )
        ],
        rerank_error=True,
    )

    assert results == []


@pytest.mark.django_db
def test_the_answer_says_not_found_instead_of_citing_an_unrelated_chunk():
    user = UserFactory()

    with (
        patch(
            "api.services.department_has_searchable_content",
            return_value=True,
        ),
        patch(
            "api.services.semantic_search",
            return_value=[semantic_hit(1, "SELECT firstname FROM HR.Employees")],
        ),
        patch("api.services.keyword_search", return_value=[]),
        patch(
            "api.services.rerank_results",
            side_effect=rerank_to(-7.2),
        ),
        patch("api.services.ai_service_post") as post,
    ):
        result = generate_rag_answer(
            "how many days do I have to submit receipts",
            user=user,
        )

    # The model is never asked: there is nothing to answer from.
    post.assert_not_called()
    assert result["no_documents"] is True
    assert result["reason"] == NO_MATCHING_CHUNKS
    assert result["answer"] == NO_DOCUMENTS_MESSAGE
    assert result["citations"] == []


@pytest.mark.django_db
def test_the_stream_emits_no_documents_instead_of_citing_an_unrelated_chunk():
    user = UserFactory()

    with (
        patch(
            "api.services.department_has_searchable_content",
            return_value=True,
        ),
        patch(
            "api.services.semantic_search",
            return_value=[semantic_hit(1, "SELECT firstname FROM HR.Employees")],
        ),
        patch("api.services.keyword_search", return_value=[]),
        patch(
            "api.services.rerank_results",
            side_effect=rerank_to(-7.2),
        ),
        patch("api.services.ai_service_post") as post,
    ):
        events = list(
            generate_rag_stream(
                "how many days do I have to submit receipts",
                user=user,
            )
        )

    post.assert_not_called()
    assert events[0]["type"] == "no_documents"
    assert events[0]["reason"] == NO_MATCHING_CHUNKS
    assert events[-1] == {"type": "done"}


@pytest.mark.django_db
def test_a_relevant_answer_still_reaches_the_model():
    user = UserFactory()
    response = Mock()
    response.json.return_value = {"answer": "Thirty days. [1]"}
    response.raise_for_status.return_value = None

    with (
        patch(
            "api.services.department_has_searchable_content",
            return_value=True,
        ),
        patch(
            "api.services.semantic_search",
            return_value=[
                semantic_hit(
                    1,
                    "Receipts must be submitted within 30 days.",
                )
            ],
        ),
        patch("api.services.keyword_search", return_value=[]),
        patch(
            "api.services.rerank_results",
            side_effect=rerank_to(6.59),
        ),
        patch(
            "api.services.ai_service_post",
            return_value=response,
        ) as post,
        patch("api.services.build_citations", return_value=[]),
    ):
        result = generate_rag_answer(
            "how many days do I have to submit receipts",
            user=user,
        )

    post.assert_called_once()
    assert result["answer"] == "Thirty days. [1]"
    assert result.get("no_documents") is not True
