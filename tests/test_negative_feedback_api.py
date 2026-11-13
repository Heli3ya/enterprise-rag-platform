"""
Sub-task 3 — GET /api/admin/quality-feedback/

The grid is the part of the dashboard that turns a percentage into a
fix. These tests pin down what it may show (negative verdicts only, one
tenant only), what it must carry per row (question, answer, comment,
department), and that paging through it does not multiply queries.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import AnswerFeedback
from tests.factories import (
    AdminFactory,
    AnswerFeedbackFactory,
    ChatAnswerFactory,
    DepartmentFactory,
    TenantFactory,
    UserFactory,
)


GRID_URL = "/api/admin/quality-feedback/"


@pytest.fixture(autouse=True)
def isolated_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tenant(db):
    return TenantFactory()


@pytest.fixture
def department(tenant):
    return DepartmentFactory(tenant=tenant)


@pytest.fixture
def admin(department):
    return AdminFactory(department=department)


@pytest.fixture
def member(department):
    return UserFactory(department=department)


@pytest.fixture
def admin_client(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def complain(user, comment="", question=None, answer_text=None, days_ago=0):
    answer = ChatAnswerFactory(user=user)

    if question is not None:
        answer.question = question
        answer.save(update_fields=["question"])

    if answer_text is not None:
        answer.answer = answer_text
        answer.save(update_fields=["answer"])

    feedback = AnswerFeedbackFactory(
        answer=answer,
        user=user,
        tenant=user.tenant,
        is_positive=False,
        user_comment=comment,
    )

    if days_ago:
        AnswerFeedback.objects.filter(pk=feedback.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago),
        )

    return feedback


# -- access control ---------------------------------------------------


@pytest.mark.django_db
def test_anonymous_caller_is_rejected():
    response = APIClient().get(GRID_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_member_is_forbidden(member):
    client = APIClient()
    client.force_authenticate(user=member)

    assert client.get(GRID_URL).status_code == 403


# -- what the grid contains -------------------------------------------


@pytest.mark.django_db
def test_only_thumbs_down_rows_are_listed(admin_client, member):
    complain(member, comment="This is wrong.")
    ChatAnswerFactory(user=member)

    payload = admin_client.get(GRID_URL).json()

    assert payload["count"] == 1
    assert payload["results"][0]["user_comment"] == "This is wrong."


@pytest.mark.django_db
def test_each_row_carries_the_context_needed_to_act(
    admin_client,
    member,
    department,
):
    """
    A thumbs-down without the question and the answer text is not
    actionable, so both travel with the row.
    """

    complain(
        member,
        comment="The notice period is 30 days, not 60.",
        question="What is the notice period?",
        answer_text="The notice period is 60 days.",
    )

    row = admin_client.get(GRID_URL).json()["results"][0]

    assert row["question"] == "What is the notice period?"
    assert row["answer_text"] == "The notice period is 60 days."
    assert row["user_comment"] == "The notice period is 30 days, not 60."
    assert row["username"] == member.username
    assert row["department_id"] == department.id
    assert row["department_name"] == department.name
    assert row["citation_count"] == 0


@pytest.mark.django_db
def test_newest_complaint_comes_first(admin_client, member):
    complain(member, comment="older")
    complain(member, comment="newer")

    comments = [
        row["user_comment"]
        for row in admin_client.get(GRID_URL).json()["results"]
    ]

    assert comments[0] == "newer"


@pytest.mark.django_db
def test_another_tenants_complaints_are_invisible(
    admin_client,
    member,
):
    outsider_tenant = TenantFactory()
    outsider = UserFactory(
        department=DepartmentFactory(tenant=outsider_tenant),
        tenant=outsider_tenant,
    )

    complain(member, comment="ours")
    complain(outsider, comment="theirs")

    payload = admin_client.get(GRID_URL).json()

    assert payload["count"] == 1
    assert payload["results"][0]["user_comment"] == "ours"


# -- pagination -------------------------------------------------------


@pytest.mark.django_db
def test_default_page_holds_twenty_rows(admin_client, member):
    for index in range(25):
        complain(member, comment=f"issue {index}")

    payload = admin_client.get(GRID_URL).json()

    assert payload["count"] == 25
    assert len(payload["results"]) == 20
    assert payload["next"] is not None
    assert payload["previous"] is None

    second_page = admin_client.get(GRID_URL, {"page": 2}).json()

    assert len(second_page["results"]) == 5
    assert second_page["next"] is None


@pytest.mark.django_db
def test_page_size_is_capped(admin_client, member):
    """
    `?page_size=5000` must not be able to ask for the whole table.
    """

    for index in range(120):
        complain(member, comment=f"issue {index}")

    payload = admin_client.get(GRID_URL, {"page_size": 5000}).json()

    assert len(payload["results"]) == 100


# -- filters ----------------------------------------------------------


@pytest.mark.django_db
def test_department_filter(admin_client, tenant, department, member):
    other_department = DepartmentFactory(tenant=tenant)
    other_member = UserFactory(
        department=other_department,
        tenant=tenant,
    )

    complain(member, comment="ours")
    complain(other_member, comment="theirs")

    payload = admin_client.get(
        GRID_URL,
        {"department_id": other_department.id},
    ).json()

    assert payload["count"] == 1
    assert payload["results"][0]["user_comment"] == "theirs"


@pytest.mark.django_db
def test_search_matches_the_comment_the_question_or_the_answer(
    admin_client,
    member,
):
    complain(member, comment="wrong notice period")
    complain(
        member,
        comment="",
        question="How do I claim reimbursement?",
        answer_text="Use the finance portal.",
    )

    by_comment = admin_client.get(
        GRID_URL,
        {"search": "notice"},
    ).json()

    assert by_comment["count"] == 1

    by_question = admin_client.get(
        GRID_URL,
        {"search": "reimbursement"},
    ).json()

    assert by_question["count"] == 1
    assert by_question["results"][0]["question"].startswith("How do I")

    by_answer = admin_client.get(
        GRID_URL,
        {"search": "finance portal"},
    ).json()

    assert by_answer["count"] == 1


@pytest.mark.django_db
def test_has_comment_filter(admin_client, member):
    complain(member, comment="explained")
    complain(member, comment="")

    with_comment = admin_client.get(
        GRID_URL,
        {"has_comment": "true"},
    ).json()

    assert with_comment["count"] == 1
    assert with_comment["results"][0]["user_comment"] == "explained"


@pytest.mark.django_db
def test_date_range_filter(admin_client, member):
    complain(member, comment="recent")
    complain(member, comment="old", days_ago=40)

    payload = admin_client.get(
        GRID_URL,
        {"date_from": timezone.localdate().isoformat()},
    ).json()

    assert payload["count"] == 1
    assert payload["results"][0]["user_comment"] == "recent"


@pytest.mark.django_db
def test_malformed_date_is_rejected(admin_client):
    response = admin_client.get(GRID_URL, {"date_from": "13-11-2026"})

    assert response.status_code == 400
    assert "date_from" in response.json()["error"]


# -- cost -------------------------------------------------------------


@pytest.mark.django_db
def test_page_cost_does_not_grow_with_row_count(
    django_assert_num_queries,
    admin,
    member,
):
    """
    Two queries: the count, and the page itself. The serializer touches
    the answer, its author and that author's department, so without
    `select_related` this would be 2 + 3N — the classic N+1 that only
    shows up once a tenant has a few thousand complaints.
    """

    for index in range(40):
        complain(member, comment=f"issue {index}")

    client = APIClient()
    client.force_authenticate(user=admin)

    with django_assert_num_queries(2):
        payload = client.get(GRID_URL, {"page_size": 40}).json()

    assert len(payload["results"]) == 40
