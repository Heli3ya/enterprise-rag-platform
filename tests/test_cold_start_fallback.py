"""
Sub-task 1 — the backend must stop before the LLM when there is
nothing to answer from.

The contract under test:

* an empty department costs **zero** outbound AI calls (not even the
  query embedding),
* a populated department with no matching chunk skips the generation
  step,
* both cases end in a single `no_documents` event that carries a
  machine-readable `reason`, and never in a `token` event,
* no answer row is stored, so a "no documents" message cannot be rated
  and cannot leak into the training export.

`requests.post` is the single chokepoint for embeddings, reranking and
generation, so asserting it was never called is the strongest possible
statement about cost.
"""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from api.models import ChatAnswer
from api.services import (
    EMPTY_DEPARTMENT,
    NO_DOCUMENTS_MESSAGE,
    NO_MATCHING_CHUNKS,
    generate_rag_answer,
    generate_rag_stream,
)
from tests.factories import (
    AdminFactory,
    DepartmentFactory,
    DocumentChunkFactory,
    UserFactory,
)


CHAT_URL = "/api/chat/ask/"
ASK_URL = "/api/query/ask/"


def read_stream(response):
    """Drain a StreamingHttpResponse into one string."""

    return b"".join(response.streaming_content).decode("utf-8")


@pytest.fixture
def empty_department_user(db):
    """A member whose department has no documents at all."""

    return UserFactory()


@pytest.fixture
def populated_user(db):
    """A member whose department has exactly one indexed chunk."""

    user = UserFactory()
    DocumentChunkFactory(
        document__department=user.department,
        document__tenant=user.tenant,
        document__uploaded_by=user,
        content="Annual leave is 20 days per year.",
    )

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


# -- service layer ------------------------------------------------------


@pytest.mark.django_db
def test_empty_department_costs_no_ai_call(empty_department_user):
    with patch("api.services.requests.post") as post:
        events = list(
            generate_rag_stream("What is the leave policy?", user=empty_department_user)
        )

    post.assert_not_called()

    assert events == [
        {
            "type": "no_documents",
            "reason": EMPTY_DEPARTMENT,
            "message": NO_DOCUMENTS_MESSAGE,
        },
        # The stream must always terminate, otherwise the client keeps
        # showing its "thinking" indicator.
        {"type": "done"},
    ]


@pytest.mark.django_db
def test_empty_department_answer_is_explicit_and_citation_free(empty_department_user):
    with patch("api.services.requests.post") as post:
        result = generate_rag_answer("What is the leave policy?", user=empty_department_user)

    post.assert_not_called()

    assert result["no_documents"] is True
    assert result["reason"] == EMPTY_DEPARTMENT
    assert result["answer"] == NO_DOCUMENTS_MESSAGE
    assert result["citations"] == []


@pytest.mark.django_db
def test_retrieval_miss_skips_generation_but_still_reports_no_documents(populated_user):
    # The department has content, so the readiness probe passes; the
    # search itself finds nothing relevant.
    with (
        patch("api.services.hybrid_search", return_value=[]) as search,
        patch("api.services.requests.post") as post,
    ):
        events = list(generate_rag_stream("Unrelated question", user=populated_user))

    search.assert_called_once()
    post.assert_not_called()

    assert events == [
        {
            "type": "no_documents",
            "reason": NO_MATCHING_CHUNKS,
            "message": NO_DOCUMENTS_MESSAGE,
        },
        {"type": "done"},
    ]


@pytest.mark.django_db
def test_readiness_probe_runs_before_the_search(populated_user):
    """An empty department must not even reach the retrieval stage."""

    empty_user = UserFactory()

    with (
        patch("api.services.hybrid_search") as search,
        patch("api.services.requests.post") as post,
    ):
        list(generate_rag_stream("Anything", user=empty_user))

    search.assert_not_called()
    post.assert_not_called()


# -- HTTP layer ---------------------------------------------------------


@pytest.mark.django_db
def test_chat_stream_emits_no_documents_instead_of_tokens(empty_department_user):
    with patch("api.services.requests.post") as post:
        response = client_for(empty_department_user).post(
            CHAT_URL,
            {"question": "What is the leave policy?", "conversation_id": "cold-1"},
            format="json",
        )

        body = read_stream(response)

    post.assert_not_called()

    assert response.status_code == 200
    assert "event: meta" in body
    assert "event: no_documents" in body
    assert '"reason": "empty_department"' in body
    assert NO_DOCUMENTS_MESSAGE in body
    assert "event: token" not in body
    assert "event: done" in body

    # Nothing to rate, so nothing is stored.
    assert ChatAnswer.objects.count() == 0


@pytest.mark.django_db
def test_chat_stream_persists_a_real_answer(populated_user):
    """Regression guard: the happy path is unchanged."""

    llm_response = MagicMock()
    llm_response.iter_content.return_value = ["Annual leave is 20 days."]

    with (
        patch(
            "api.services.hybrid_search",
            return_value=[{"chunk_id": 1, "content": "Annual leave is 20 days."}],
        ),
        patch("api.services.requests.post", return_value=llm_response),
        patch("api.services.build_citations", return_value=[]),
    ):
        response = client_for(populated_user).post(
            CHAT_URL,
            {"question": "How much leave?", "conversation_id": "warm-1"},
            format="json",
        )

        body = read_stream(response)

    assert "event: token" in body
    assert "event: no_documents" not in body

    stored = ChatAnswer.objects.get()
    assert stored.answer == "Annual leave is 20 days."
    assert stored.is_complete is True


@pytest.mark.django_db
def test_query_ask_reports_no_documents_without_an_answer_id(empty_department_user):
    with patch("api.services.requests.post") as post:
        response = client_for(empty_department_user).post(
            ASK_URL,
            {"query_text": "What is the leave policy?"},
            format="json",
        )

    post.assert_not_called()

    assert response.status_code == 200

    body = response.json()
    assert body["no_documents"] is True
    assert body["reason"] == EMPTY_DEPARTMENT
    assert body["answer"] == NO_DOCUMENTS_MESSAGE
    assert body["citations"] == []
    assert body["answer_id"] is None

    assert ChatAnswer.objects.count() == 0


@pytest.mark.django_db
def test_query_ask_returns_an_answer_id_when_a_document_matched(populated_user):
    llm_response = MagicMock()
    llm_response.json.return_value = {"answer": "Annual leave is 20 days."}

    with (
        patch(
            "api.services.hybrid_search",
            return_value=[{"chunk_id": 1, "content": "Annual leave is 20 days."}],
        ),
        patch("api.services.requests.post", return_value=llm_response),
        patch("api.services.build_citations", return_value=[]),
    ):
        response = client_for(populated_user).post(
            ASK_URL,
            {"query_text": "How much leave?"},
            format="json",
        )

    assert response.status_code == 200

    body = response.json()
    assert body["no_documents"] is False
    assert body["reason"] is None
    assert body["answer_id"] is not None

    assert ChatAnswer.objects.filter(id=body["answer_id"]).exists()


@pytest.mark.django_db
def test_admin_sees_the_same_gate_as_a_member():
    """An admin with an empty department is not special-cased."""

    admin = AdminFactory()

    with patch("api.services.requests.post") as post:
        result = generate_rag_answer("Anything?", user=admin)

    post.assert_not_called()
    assert result["reason"] == EMPTY_DEPARTMENT
