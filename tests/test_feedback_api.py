import json
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from api.models import AnswerFeedback, ChatAnswer
from tests.factories import ChatAnswerFactory, UserFactory


FEEDBACK_URL = "/api/chat/feedback/"


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def post_feedback(client, answer, **overrides):
    payload = {
        "answer_id": str(answer.id),
        "is_positive": True,
    }
    payload.update(overrides)

    return client.post(FEEDBACK_URL, payload, format="json")


@pytest.mark.django_db
def test_feedback_requires_authentication():
    response = APIClient().post(
        FEEDBACK_URL,
        {"answer_id": str(uuid.uuid4()), "is_positive": True},
        format="json",
    )

    assert response.status_code == 401
    assert AnswerFeedback.objects.count() == 0


@pytest.mark.django_db
def test_feedback_is_created_and_returns_201(user, client_for):
    answer = ChatAnswerFactory(user=user)

    response = post_feedback(
        client_for,
        answer,
        is_positive=False,
        user_comment="  The answer missed the notice period.  ",
    )

    assert response.status_code == 201

    body = response.json()
    assert body["answer_id"] == str(answer.id)
    assert body["is_positive"] is False
    assert body["user_comment"] == "The answer missed the notice period."
    assert body["created_at"]

    feedback = AnswerFeedback.objects.get()
    assert feedback.answer == answer
    assert feedback.user == user
    assert feedback.tenant == user.tenant


@pytest.mark.django_db
def test_comment_is_optional(user, client_for):
    answer = ChatAnswerFactory(user=user)

    response = post_feedback(client_for, answer)

    assert response.status_code == 201
    assert response.json()["user_comment"] == ""


@pytest.mark.django_db
def test_second_feedback_for_same_answer_returns_409(user, client_for):
    answer = ChatAnswerFactory(user=user)

    first = post_feedback(client_for, answer, is_positive=True)
    second = post_feedback(client_for, answer, is_positive=False)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"] == (
        "Feedback already submitted for this answer."
    )
    assert AnswerFeedback.objects.filter(answer=answer).count() == 1


@pytest.mark.django_db
def test_feedback_for_unknown_answer_returns_404(client_for):
    response = client_for.post(
        FEEDBACK_URL,
        {"answer_id": str(uuid.uuid4()), "is_positive": True},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Answer not found."


@pytest.mark.django_db
def test_feedback_for_another_users_answer_returns_404(client_for):
    other_user = UserFactory()
    other_answer = ChatAnswerFactory(user=other_user)

    response = post_feedback(client_for, other_answer)

    assert response.status_code == 404
    assert AnswerFeedback.objects.count() == 0


@pytest.mark.django_db
def test_feedback_rejects_missing_is_positive(user, client_for):
    answer = ChatAnswerFactory(user=user)

    response = client_for.post(
        FEEDBACK_URL,
        {"answer_id": str(answer.id)},
        format="json",
    )

    assert response.status_code == 400
    assert "is_positive" in response.json()


@pytest.mark.django_db
def test_feedback_rejects_malformed_answer_id(client_for):
    response = client_for.post(
        FEEDBACK_URL,
        {"answer_id": "not-a-uuid", "is_positive": True},
        format="json",
    )

    assert response.status_code == 400
    assert "answer_id" in response.json()


@pytest.mark.django_db
def test_feedback_rejects_overlong_comment(user, client_for):
    answer = ChatAnswerFactory(user=user)

    response = post_feedback(
        client_for,
        answer,
        user_comment="x" * 2001,
    )

    assert response.status_code == 400
    assert "user_comment" in response.json()


@pytest.mark.django_db
def test_chat_stream_emits_answer_id_and_persists_answer(client_for):
    citations = [
        {
            "document_id": 3,
            "filename": "leave-policy.txt",
            "department": "HR",
            "chunk_id": 9,
        }
    ]
    events = [
        {"type": "token", "content": "Employees "},
        {"type": "token", "content": "receive 20 days."},
        {"type": "citations", "citations": citations},
        {"type": "done"},
    ]

    with patch(
        "api.views.generate_rag_stream",
        return_value=iter(events),
    ):
        response = client_for.post(
            "/api/chat/ask/",
            {
                "question": "How much annual leave do I get?",
                "conversation_id": "conversation-stream-1",
            },
            format="json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert "event: meta" in body

    meta_data = [
        line[len("data:"):].strip()
        for line in body.split("\n")
        if line.startswith("data:") and "answer_id" in line
    ][0]
    answer_id = json.loads(meta_data)["answer_id"]

    stored = ChatAnswer.objects.get(id=answer_id)
    assert stored.answer == "Employees receive 20 days."
    assert stored.citations == citations
    assert stored.conversation_id == "conversation-stream-1"
    assert stored.is_complete is True
    assert stored.user == client_for.handler._force_user


@pytest.mark.django_db
def test_streamed_answer_accepts_feedback(client_for):
    events = [
        {"type": "token", "content": "Twenty days."},
        {"type": "citations", "citations": []},
        {"type": "done"},
    ]

    with patch(
        "api.views.generate_rag_stream",
        return_value=iter(events),
    ):
        response = client_for.post(
            "/api/chat/ask/",
            {
                "question": "How much annual leave?",
                "conversation_id": "conversation-stream-2",
            },
            format="json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")

    meta_data = [
        line[len("data:"):].strip()
        for line in body.split("\n")
        if line.startswith("data:") and "answer_id" in line
    ][0]
    answer_id = json.loads(meta_data)["answer_id"]

    feedback_response = client_for.post(
        FEEDBACK_URL,
        {"answer_id": answer_id, "is_positive": True},
        format="json",
    )

    assert feedback_response.status_code == 201
    assert AnswerFeedback.objects.filter(answer_id=answer_id).count() == 1


@pytest.mark.django_db
def test_partial_answer_is_stored_but_marked_incomplete(client_for):
    events = [
        {"type": "token", "content": "Employees receive "},
        {"type": "error", "message": "LLM request timed out"},
    ]

    with patch(
        "api.views.generate_rag_stream",
        return_value=iter(events),
    ):
        response = client_for.post(
            "/api/chat/ask/",
            {
                "question": "How much annual leave?",
                "conversation_id": "conversation-stream-3",
            },
            format="json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")

    assert "event: error" in body

    meta_data = [
        line[len("data:"):].strip()
        for line in body.split("\n")
        if line.startswith("data:") and "answer_id" in line
    ][0]
    answer_id = json.loads(meta_data)["answer_id"]

    stored = ChatAnswer.objects.get(id=answer_id)
    assert stored.answer == "Employees receive "
    assert stored.is_complete is False


@pytest.mark.django_db
def test_rag_query_returns_answer_id(client_for):
    result = {
        "answer": "Twenty days per year.",
        "citations": [],
    }

    with patch(
        "api.views.generate_rag_answer",
        return_value=result,
    ):
        response = client_for.post(
            "/api/query/ask/",
            {
                "query_text": "How much annual leave?",
                "conversation_id": "conversation-rag-1",
            },
            format="json",
        )

    assert response.status_code == 200

    body = response.json()
    assert body["answer_id"]

    stored = ChatAnswer.objects.get(id=body["answer_id"])
    assert stored.answer == "Twenty days per year."
    assert stored.is_complete is True
    assert stored.conversation_id == "conversation-rag-1"
