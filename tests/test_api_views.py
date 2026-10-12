
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from api.services import build_rag_prompt
from tests.factories import AdminFactory, DocumentChunkFactory


@pytest.fixture
def admin_client(db):
    user = AdminFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_create_embeddings_returns_400_when_chunk_ids_missing(admin_client):
    response = admin_client.post(
        "/api/embeddings/create/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "chunk_ids is required."


@pytest.mark.django_db
def test_create_embeddings_returns_404_when_no_chunks_exist(admin_client):
    response = admin_client.post(
        "/api/embeddings/create/",
        {"chunk_ids": [999999]},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error"] == "No valid document chunks found."


@pytest.mark.django_db
def test_create_embeddings_returns_502_when_ai_service_fails(admin_client):
    chunk = DocumentChunkFactory()

    with patch(
        "api.views.generate_embeddings",
        side_effect=RuntimeError("AI service unavailable"),
    ):
        response = admin_client.post(
            "/api/embeddings/create/",
            {"chunk_ids": [chunk.id]},
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "AI service unavailable"


@pytest.mark.django_db
def test_create_embeddings_saves_embeddings_successfully(admin_client):
    from documents.models import Embedding

    chunk = DocumentChunkFactory()

    with patch(
        "api.views.generate_embeddings",
        return_value=([[0.1] * 384], 384),
    ):
        response = admin_client.post(
            "/api/embeddings/create/",
            {"chunk_ids": [chunk.id]},
            format="json",
        )

    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 1
    assert len(data["embeddings"]) == 1
    assert data["embeddings"][0]["chunk_id"] == chunk.id
    assert data["embeddings"][0]["dimension"] == 384

    embedding = Embedding.objects.get(chunk=chunk)
    assert embedding.model_name == "intfloat/multilingual-e5-small"
    assert len(embedding.embedding_vector) == 384


def test_semantic_search_returns_400_when_query_is_missing(admin_client):
    response = admin_client.post(
        "/api/search/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "query is required."


def test_semantic_search_returns_400_when_query_is_blank(admin_client):
    response = admin_client.post(
        "/api/search/",
        {"query": "   "},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "query is required."


def test_semantic_search_returns_502_when_search_fails(admin_client):
    with patch(
        "api.views.hybrid_search",
        side_effect=RuntimeError("Search service unavailable"),
    ):
        response = admin_client.post(
            "/api/search/",
            {"query": "annual leave"},
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "Search service unavailable"


def test_semantic_search_returns_results_from_chunk_object(admin_client):
    result = {
        "result": SimpleNamespace(
            chunk=SimpleNamespace(
                document_id=21,
                document=SimpleNamespace(title="Leave policy"),
                chunk_index=3,
            )
        ),
        "chunk_id": 42,
        "score": 0.87654321,
        "content": "Annual leave requires approval.",
    }

    with patch("api.views.hybrid_search", return_value=[result]) as search:
        response = admin_client.post(
            "/api/search/",
            {"query": " annual leave "},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == {
        "query": "annual leave",
        "results": [
            {
                "document_id": 21,
                "document_title": "Leave policy",
                "chunk_id": 42,
                "chunk_index": 3,
                "score": 0.876543,
                "content": "Annual leave requires approval.",
            }
        ],
    }
    search.assert_called_once_with("annual leave", limit=5)


def test_semantic_search_returns_results_from_direct_chunk_object(admin_client):
    result = {
        "result": SimpleNamespace(
            document_id=31,
            document=SimpleNamespace(title="Remote work policy"),
            chunk_index=2,
        ),
        "chunk_id": 51,
        "score": 0.5,
        "content": "Remote work requires approval.",
    }

    with patch("api.views.hybrid_search", return_value=[result]):
        response = admin_client.post(
            "/api/search/",
            {"query": "remote work"},
            format="json",
        )

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["document_id"] == 31
    assert item["document_title"] == "Remote work policy"
    assert item["chunk_id"] == 51
    assert item["chunk_index"] == 2
    assert item["score"] == 0.5

from types import SimpleNamespace


@pytest.mark.django_db
def test_search_query_returns_502_when_search_fails(admin_client):
    with patch(
        "api.views.hybrid_search",
        side_effect=RuntimeError("Search service unavailable"),
    ):
        response = admin_client.post(
            "/api/query/search/",
            {"query_text": "annual leave", "top_k": 5},
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "Search service unavailable"


@pytest.mark.django_db
def test_search_query_saves_valid_results(admin_client):
    from documents.models import QueryResult, SearchQuery

    chunk = DocumentChunkFactory()
    chunk.document.is_public = True
    chunk.document.save(update_fields=["is_public"])

    result = {
        "chunk_id": chunk.id,
        "score": 0.8,
        "rerank_score": 0.9,
        "content": chunk.content,
        "result": SimpleNamespace(
            chunk=SimpleNamespace(
                document_id=chunk.document_id,
                document=chunk.document,
            )
        ),
    }

    with (
        patch("api.views.hybrid_search", return_value=[result]) as search,
        patch("api.views.create_audit_log") as audit,
    ):
        response = admin_client.post(
            "/api/query/search/",
            {"query_text": "annual leave", "top_k": 5},
            format="json",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["query_text"] == "annual leave"
    assert len(data["results"]) == 1
    assert data["results"][0]["chunk_id"] == chunk.id
    assert data["results"][0]["document_id"] == chunk.document_id
    assert data["results"][0]["score"] == 0.9

    saved_query = SearchQuery.objects.get(query_text="annual leave")
    assert saved_query.user == admin_client.handler._force_user
    assert QueryResult.objects.filter(
        query=saved_query,
        chunk_id=chunk.id,
        relevance_score=0.9,
    ).exists()

    search.assert_called_once()
    audit.assert_called_once()


@pytest.mark.django_db
def test_search_query_filters_results_with_nonpositive_rerank_score(admin_client):
    from documents.models import SearchQuery, QueryResult

    chunk = DocumentChunkFactory()
    chunk.document.is_public = True
    chunk.document.save(update_fields=["is_public"])

    result = {
        "chunk_id": chunk.id,
        "rerank_score": 0,
        "content": chunk.content,
        "result": SimpleNamespace(
            chunk=SimpleNamespace(
                document_id=chunk.document_id,
                document=chunk.document,
            )
        ),
    }

    with (
        patch("api.views.hybrid_search", return_value=[result]),
        patch("api.views.create_audit_log"),
    ):
        response = admin_client.post(
            "/api/query/search/",
            {"query_text": "annual leave", "top_k": 5},
            format="json",
        )

    assert response.status_code == 200
    assert response.json()["results"] == []

    saved_query = SearchQuery.objects.get(query_text="annual leave")
    assert not QueryResult.objects.filter(query=saved_query).exists()


@pytest.mark.django_db
def test_rag_query_returns_502_when_rag_service_fails(admin_client):
    with patch(
        "api.views.generate_rag_answer",
        side_effect=RuntimeError("RAG service unavailable"),
    ):
        response = admin_client.post(
            "/api/query/ask/",
            {"query_text": "annual leave", "top_k": 5},
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "RAG service unavailable"


@pytest.mark.django_db
def test_rag_query_returns_answer_and_citations(admin_client):
    citations = [
        {
            "document_id": 8,
            "filename": "leave-policy.txt",
            "department": "HR",
            "chunk_id": 15,
        }
    ]

    with (
        patch(
            "api.views.generate_rag_answer",
            return_value={
                "answer": "Annual leave requires approval. [15]",
                "citations": citations,
            },
        ) as generate_answer,
        patch("api.views.create_audit_log") as audit,
    ):
        response = admin_client.post(
            "/api/query/ask/",
            {"query_text": "annual leave", "top_k": 5},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == {
        "query_text": "annual leave",
        "answer": "Annual leave requires approval. [15]",
        "citations": citations,
    }
    generate_answer.assert_called_once()
    audit.assert_called_once()

@pytest.mark.django_db
def test_chat_ask_streams_tokens_citations_and_done(admin_client):
    citations = [
        {
            "document_id": 8,
            "filename": "leave-policy.txt",
            "department": "HR",
            "chunk_id": 15,
        }
    ]
    events = [
        {"type": "token", "content": "Annual "},
        {"type": "token", "content": "leave."},
        {"type": "citations", "citations": citations},
        {"type": "done"},
    ]

    with patch("api.views.generate_rag_stream", return_value=iter(events)) as stream:
        response = admin_client.post(
            "/api/chat/ask/",
            {
                "question": "What is the annual leave policy?",
                "conversation_id": "test-conversation-1",
            },
            format="json",
        )
        response_content = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert "Annual " in response_content
    assert "leave." in response_content
    assert "leave-policy.txt" in response_content
    assert "event: done" in response_content
    stream.assert_called_once()


@pytest.mark.django_db
def test_chat_ask_streams_error_event(admin_client):
    events = [
        {
            "type": "error",
            "message": "No relevant documents were found.",
        }
    ]

    with patch("api.views.generate_rag_stream", return_value=iter(events)):
        response = admin_client.post(
            "/api/chat/ask/",
            {
                "question": "A question with no matching documents",
                "conversation_id": "test-conversation-2",
            },
            format="json",
        )
        response_content = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert "event: error" in response_content
    assert "No relevant documents were found." in response_content


@pytest.mark.django_db
def test_chat_ask_streams_error_when_generator_raises(admin_client):
    def failing_stream(*args, **kwargs):
        raise RuntimeError("Simulated streaming failure")
        yield

    with patch("api.views.generate_rag_stream", side_effect=failing_stream):
        response = admin_client.post(
            "/api/chat/ask/",
            {
                "question": "What is the policy?",
                "conversation_id": "test-conversation-3",
            },
            format="json",
        )
        response_content = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert "event: error" in response_content
    assert "Simulated streaming failure" in response_content


@pytest.mark.django_db
def test_audit_logs_returns_logs_for_admin(admin_client):
    from api.models import AuditLog

    user = admin_client.handler._force_user
    AuditLog.objects.create(user=user, action="SEARCH")

    response = admin_client.get("/api/audit-logs/")

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["action"] == "SEARCH"


@pytest.mark.django_db
def test_audit_logs_filters_by_user_id(admin_client):
    from api.models import AuditLog
    from tests.factories import UserFactory

    first_user = admin_client.handler._force_user
    second_user = UserFactory()

    AuditLog.objects.create(user=first_user, action="SEARCH")
    AuditLog.objects.create(user=second_user, action="UPLOAD")

    response = admin_client.get(
        "/api/audit-logs/",
        {"user_id": second_user.id},
    )

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["action"] == "UPLOAD"


@pytest.mark.django_db
def test_audit_logs_filters_by_date_range(admin_client):
    from datetime import timedelta

    from django.utils import timezone
    from api.models import AuditLog

    user = admin_client.handler._force_user
    now = timezone.now()

    old_log = AuditLog.objects.create(user=user, action="OLD")
    current_log = AuditLog.objects.create(user=user, action="CURRENT")

    AuditLog.objects.filter(pk=old_log.pk).update(
        timestamp=now - timedelta(days=10)
    )
    AuditLog.objects.filter(pk=current_log.pk).update(timestamp=now)

    response = admin_client.get(
        "/api/audit-logs/",
        {
            "date_from": (now - timedelta(days=1)).date().isoformat(),
            "date_to": now.date().isoformat(),
        },
    )

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["action"] == "CURRENT"


@pytest.mark.django_db
def test_audit_logs_rejects_invalid_date_from(admin_client):
    response = admin_client.get(
        "/api/audit-logs/",
        {"date_from": "not-a-date"},
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid date_from format. Use YYYY-MM-DD."


@pytest.mark.django_db
def test_audit_logs_rejects_invalid_date_to(admin_client):
    response = admin_client.get(
        "/api/audit-logs/",
        {"date_to": "not-a-date"},
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid date_to format. Use YYYY-MM-DD."


@pytest.mark.django_db
def test_current_user_returns_authenticated_user_and_department(admin_client):
    response = admin_client.get("/api/auth/me/")

    assert response.status_code == 200
    assert response.data["username"]
    assert response.data["role"] == "Admin"
    assert "department_id" in response.data
    assert "department_name" in response.data


@pytest.mark.django_db
def test_current_user_returns_null_department_when_user_has_none(admin_client):
    from tests.factories import UserFactory

    user = UserFactory(department=None)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/auth/me/")

    assert response.status_code == 200
    assert response.data["department_id"] is None
    assert response.data["department_name"] is None
