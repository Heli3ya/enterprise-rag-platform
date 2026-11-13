"""
Sub-task 1 — GET /api/admin/quality-metrics/

The point of these tests is not only "the endpoint answers". It is that
the *number* means what the dashboard claims it means, that the number
is scoped to one tenant, and that reading it twice does not cost two
full aggregations.
"""

from datetime import date, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import AnswerFeedback
from api.quality import get_quality_metrics
from tests.factories import (
    AdminFactory,
    AnswerFeedbackFactory,
    ChatAnswerFactory,
    DepartmentFactory,
    TenantFactory,
    UserFactory,
)


METRICS_URL = "/api/admin/quality-metrics/"
FEEDBACK_URL = "/api/chat/feedback/"


@pytest.fixture(autouse=True)
def isolated_cache():
    """
    The metrics are cached in Redis for 60 seconds.

    Without this, one test's payload would be served to the next one and
    every assertion about counts would be a coin flip.
    """

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


def rate(user, is_positive, comment="", days_ago=0):
    """Create an answer plus a verdict on it, optionally backdated."""

    answer = ChatAnswerFactory(user=user)
    feedback = AnswerFeedbackFactory(
        answer=answer,
        user=user,
        tenant=user.tenant,
        is_positive=is_positive,
        user_comment=comment,
    )

    if days_ago:
        AnswerFeedback.objects.filter(pk=feedback.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago),
        )

    return feedback


def get_metrics(client, **params):
    return client.get(METRICS_URL, params)


# -- access control ---------------------------------------------------


@pytest.mark.django_db
def test_anonymous_caller_is_rejected():
    response = APIClient().get(METRICS_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_member_is_forbidden(member):
    client = APIClient()
    client.force_authenticate(user=member)

    response = get_metrics(client)

    assert response.status_code == 403


@pytest.mark.django_db
def test_user_without_a_tenant_is_forbidden():
    admin = AdminFactory(department=None, tenant=None)
    client = APIClient()
    client.force_authenticate(user=admin)

    response = get_metrics(client)

    assert response.status_code == 403


# -- the headline number ----------------------------------------------


@pytest.mark.django_db
def test_satisfaction_rate_is_positive_over_rated(admin_client, member):
    rate(member, True)
    rate(member, True)
    rate(member, True)
    rate(member, False, comment="Wrong notice period.")

    totals = get_metrics(admin_client).json()["totals"]

    assert totals["rated"] == 4
    assert totals["positive"] == 3
    assert totals["negative"] == 1
    assert totals["satisfaction_rate"] == 75.0


@pytest.mark.django_db
def test_unrated_answers_do_not_drag_the_rate_down(
    admin_client,
    member,
):
    """
    The single most important semantic decision of this endpoint.

    Ten people asked, two rated, both happy. The quality score is 100%,
    not 20%: the other eight gave no verdict, so they are not evidence
    of failure. Adoption is reported separately by `response_rate`.
    """

    for _ in range(8):
        ChatAnswerFactory(user=member)

    rate(member, True)
    rate(member, True)

    totals = get_metrics(admin_client).json()["totals"]

    assert totals["answers"] == 10
    assert totals["rated"] == 2
    assert totals["satisfaction_rate"] == 100.0
    assert totals["response_rate"] == 20.0
    assert totals["positive_share_of_answers"] == 20.0


@pytest.mark.django_db
def test_rates_are_null_when_there_is_nothing_to_divide(
    admin_client,
):
    """
    "Nobody rated anything" must not render as 0% in the dashboard.
    """

    totals = get_metrics(admin_client).json()["totals"]

    assert totals["rated"] == 0
    assert totals["satisfaction_rate"] is None
    assert totals["response_rate"] is None
    assert totals["positive_share_of_answers"] is None


@pytest.mark.django_db
def test_negative_feedback_with_a_comment_is_counted(
    admin_client,
    member,
):
    rate(member, False, comment="The citation is from an old policy.")
    rate(member, False, comment="")
    rate(member, True)

    totals = get_metrics(admin_client).json()["totals"]

    assert totals["negative"] == 2
    assert totals["negative_with_comment"] == 1


# -- window -----------------------------------------------------------


@pytest.mark.django_db
def test_feedback_outside_the_window_is_ignored(
    admin_client,
    member,
):
    rate(member, True)
    rate(member, False, comment="Stale verdict.", days_ago=40)

    totals = get_metrics(admin_client, days=30).json()["totals"]

    assert totals["rated"] == 1
    assert totals["satisfaction_rate"] == 100.0


@pytest.mark.django_db
def test_window_is_reported_back_to_the_client(admin_client):
    payload = get_metrics(admin_client, days=7).json()

    window = payload["window"]

    assert window["days"] == 7
    assert window["granularity"] == "day"
    assert window["date_to"] == timezone.localdate().isoformat()


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["0", "366", "-1", "abc"])
def test_invalid_window_is_rejected(admin_client, value):
    response = get_metrics(admin_client, days=value)

    assert response.status_code == 400
    assert "days" in response.json()["error"]


# -- trend ------------------------------------------------------------


@pytest.mark.django_db
def test_trend_has_exactly_one_point_per_day(admin_client, member):
    rate(member, True)

    trend = get_metrics(admin_client, days=7).json()["trend"]

    assert len(trend) == 7
    assert trend[-1]["date"] == timezone.localdate().isoformat()
    assert trend[-1]["rated"] == 1
    assert trend[-1]["satisfaction_rate"] == 100.0


@pytest.mark.django_db
def test_empty_days_are_null_not_zero(admin_client, member):
    """
    A day with no ratings must break the line, not dip to 0%.

    Filling those buckets with 0 would draw a cliff every weekend and
    make the chart lie about quality.
    """

    rate(member, True, days_ago=3)

    trend = get_metrics(admin_client, days=7).json()["trend"]

    empty_days = [point for point in trend if point["rated"] == 0]

    assert empty_days
    assert all(point["satisfaction_rate"] is None for point in empty_days)


@pytest.mark.django_db
def test_long_windows_bucket_by_week(admin_client):
    """
    365 daily points is noise on a line chart and a bigger payload than
    the screen can use, so anything past a quarter switches to weeks.
    """

    payload = get_metrics(admin_client, days=365).json()

    assert payload["window"]["granularity"] == "week"
    assert len(payload["trend"]) <= 54

    for point in payload["trend"]:
        bucket = date.fromisoformat(point["date"])

        # Weekly buckets are anchored on Monday, which is what lets the
        # frontend label the point with the week it starts.
        assert bucket.weekday() == 0


# -- per department ---------------------------------------------------


@pytest.mark.django_db
def test_department_breakdown_attributes_answers_to_the_asker(
    admin_client,
    tenant,
    department,
    member,
):
    other_department = DepartmentFactory(tenant=tenant)
    other_member = UserFactory(
        department=other_department,
        tenant=tenant,
    )

    rate(member, True)
    rate(member, False, comment="Wrong.")
    rate(other_member, True)

    breakdown = {
        row["department_id"]: row
        for row in get_metrics(admin_client).json()["by_department"]
    }

    assert breakdown[department.id]["rated"] == 2
    assert breakdown[department.id]["satisfaction_rate"] == 50.0
    assert breakdown[other_department.id]["rated"] == 1
    assert breakdown[other_department.id]["satisfaction_rate"] == 100.0


@pytest.mark.django_db
def test_departments_without_ratings_are_still_listed(
    admin_client,
    tenant,
):
    DepartmentFactory(tenant=tenant)

    breakdown = get_metrics(admin_client).json()["by_department"]

    assert breakdown
    assert all(row["rated"] == 0 for row in breakdown)
    assert all(row["satisfaction_rate"] is None for row in breakdown)


@pytest.mark.django_db
def test_department_filter_narrows_every_section(
    admin_client,
    tenant,
    department,
    member,
):
    other_department = DepartmentFactory(tenant=tenant)
    other_member = UserFactory(
        department=other_department,
        tenant=tenant,
    )

    rate(member, True)
    rate(other_member, False, comment="Wrong.")

    payload = get_metrics(
        admin_client,
        department_id=department.id,
    ).json()

    assert payload["totals"]["rated"] == 1
    assert payload["totals"]["satisfaction_rate"] == 100.0
    assert len(payload["by_department"]) == 1
    assert payload["by_department"][0]["department_id"] == department.id


@pytest.mark.django_db
def test_unknown_department_is_a_404(admin_client):
    response = get_metrics(admin_client, department_id=999999)

    assert response.status_code == 404


# -- isolation --------------------------------------------------------


@pytest.mark.django_db
def test_another_tenants_feedback_is_never_counted(
    admin_client,
    member,
):
    outsider_tenant = TenantFactory()
    outsider_department = DepartmentFactory(tenant=outsider_tenant)
    outsider = UserFactory(
        department=outsider_department,
        tenant=outsider_tenant,
    )

    rate(member, True)
    rate(outsider, False, comment="Not ours.")

    payload = get_metrics(admin_client).json()

    assert payload["totals"]["rated"] == 1
    assert payload["totals"]["negative"] == 0
    assert all(
        row["department_id"] != outsider_department.id
        for row in payload["by_department"]
    )


# -- cost -------------------------------------------------------------


@pytest.mark.django_db
def test_aggregation_stays_at_a_handful_of_queries(
    django_assert_max_num_queries,
    tenant,
    member,
):
    """
    Five queries whether the window holds one rating or a hundred
    thousand: totals, answer count, trend, department rows, department
    names. A per-day or per-department loop would grow with the data;
    this does not.
    """

    for index in range(25):
        rate(member, index % 2 == 0, comment=f"comment {index}")

    with django_assert_max_num_queries(5):
        payload = get_quality_metrics(tenant.id, 30)

    assert payload["totals"]["rated"] == 25


@pytest.mark.django_db
def test_second_read_costs_no_queries(
    django_assert_num_queries,
    tenant,
    member,
):
    rate(member, True)

    get_quality_metrics(tenant.id, 30)

    with django_assert_num_queries(0):
        payload = get_quality_metrics(tenant.id, 30)

    assert payload["totals"]["rated"] == 1


@pytest.mark.django_db
def test_new_feedback_retires_the_cached_window(
    admin_client,
    member,
):
    """
    A rating submitted now must show up on the very next dashboard load,
    not 60 seconds later.
    """

    first = get_metrics(admin_client).json()
    assert first["totals"]["rated"] == 0

    answer = ChatAnswerFactory(user=member)

    member_client = APIClient()
    member_client.force_authenticate(user=member)
    response = member_client.post(
        FEEDBACK_URL,
        {"answer_id": str(answer.id), "is_positive": False},
        format="json",
    )
    assert response.status_code == 201

    second = get_metrics(admin_client).json()

    assert second["totals"]["rated"] == 1
    assert second["totals"]["negative"] == 1
    assert second["totals"]["satisfaction_rate"] == 0.0
