"""
What happens when the reranker answers with something unexpected.

`rerank_results` used to index `payload["results"]` directly. Any 200
whose body was not that shape — a proxy's error page, a service that
was restarted onto a different contract, a handler that answers
`{"detail": ...}` with status 200 — raised `KeyError` inside the search
path and surfaced to the user as a 500.

The reranker is optional. A malformed answer must therefore be treated
like an unavailable reranker: log it, fall back to hybrid scores, keep
answering. These tests pin that, and pin that a partly broken payload
still ranks the items it did describe.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from api.services import (
    AIServiceError,
    hybrid_search,
    rerank_results,
)
from tests.factories import UserFactory


def candidate(chunk_id, content):
    return {
        "chunk_id": chunk_id,
        "score": 0.5,
        "content": content,
        "result": SimpleNamespace(content=content),
    }


def reranker_returning(payload, status_code=200):
    """Patch the HTTP call so `.json()` yields `payload`."""

    response = Mock()
    response.json.return_value = payload
    response.status_code = status_code

    return patch("api.services.ai_service_post", return_value=response)


@pytest.mark.django_db
def test_a_payload_without_results_is_an_ai_service_error():
    results = [candidate(1, "the travel policy allows three nights")]

    with reranker_returning({"detail": "internal token rejected"}):
        with pytest.raises(AIServiceError):
            rerank_results("travel policy", results)


@pytest.mark.django_db
def test_a_payload_that_is_not_an_object_is_an_ai_service_error():
    results = [candidate(1, "the travel policy allows three nights")]

    with reranker_returning(["not", "an", "object"]):
        with pytest.raises(AIServiceError):
            rerank_results("travel policy", results)


@pytest.mark.django_db
def test_a_results_key_that_is_not_a_list_is_an_ai_service_error():
    results = [candidate(1, "the travel policy allows three nights")]

    with reranker_returning({"results": "twenty"}):
        with pytest.raises(AIServiceError):
            rerank_results("travel policy", results)


@pytest.mark.django_db
def test_a_valid_payload_still_ranks_by_score():
    results = [
        candidate(1, "the travel policy allows three nights"),
        candidate(2, "the receipt deadline is thirty days"),
    ]

    payload = {
        "results": [
            {"content": "the receipt deadline is thirty days", "score": 4.2},
            {"content": "the travel policy allows three nights", "score": -1.5},
        ]
    }

    with reranker_returning(payload):
        ranked = rerank_results("receipts", results)

    assert [item["chunk_id"] for item in ranked] == [2, 1]
    assert ranked[0]["rerank_score"] == pytest.approx(4.2)


@pytest.mark.django_db
def test_items_the_reranker_did_not_describe_sort_last():
    results = [
        candidate(1, "described"),
        candidate(2, "not described"),
    ]

    payload = {"results": [{"content": "described", "score": 3.0}]}

    with reranker_returning(payload):
        ranked = rerank_results("anything", results)

    assert ranked[0]["chunk_id"] == 1
    assert ranked[1]["chunk_id"] == 2
    assert ranked[1]["rerank_score"] < ranked[0]["rerank_score"]


@pytest.mark.django_db
def test_junk_entries_inside_results_are_skipped():
    results = [candidate(1, "the travel policy allows three nights")]

    payload = {
        "results": [
            "not a dict",
            {"content": None, "score": 1.0},
            {"content": "the travel policy allows three nights", "score": "abc"},
            {"content": "the travel policy allows three nights", "score": 2.0},
        ]
    }

    with reranker_returning(payload):
        ranked = rerank_results("travel policy", results)

    # The one usable entry is the last one: the string score and the
    # null content were dropped instead of poisoning the whole call.
    assert ranked[0]["rerank_score"] == pytest.approx(2.0)


@pytest.mark.django_db
def test_search_falls_back_to_hybrid_scores_when_the_reranker_is_malformed():
    user = UserFactory()

    semantic = [
        SimpleNamespace(
            chunk_id=1,
            distance=0.1,
            chunk=SimpleNamespace(content="the travel policy allows three nights"),
        )
    ]

    with patch("api.services.semantic_search", return_value=semantic), patch(
        "api.services.keyword_search",
        return_value=[],
    ), reranker_returning({"detail": "boom"}):
        # No exception reaches the caller: a broken reranker degrades to
        # the hybrid path, exactly like a reranker that is switched off.
        results = hybrid_search("travel policy", user=user)

    assert len(results) == 1
    assert results[0]["chunk_id"] == 1
