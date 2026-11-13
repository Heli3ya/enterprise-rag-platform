"""
Quality monitoring for the admin dashboard.

Everything here is shaped by one constraint: a dashboard is read far
more often than the data changes, and it is read *aggregated*. So the
work is pushed into the database as conditional aggregation (one scan,
one round trip) instead of pulling rows into Python, and the result is
cached briefly so a page that auto-refreshes cannot turn into a query
storm.

The two numbers the panel shows are deliberately kept apart:

* `satisfaction_rate` = positive / rated. This is the honest quality
  signal: an answer nobody rated carries no verdict, and counting it as
  a failure would make the number drop every time usage grows.
* `response_rate` = rated / answers. This measures rating adoption, not
  quality, and it is shown next to the other one so the admin can see
  whether a "good" percentage rests on three votes or three thousand.
"""

import logging
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from api.models import AnswerFeedback, ChatAnswer
from departments.models import Department


logger = logging.getLogger(__name__)


DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365

# Beyond a quarter, one point per day is mostly noise on a line chart
# and up to 365 points in the payload. Weekly buckets cap the series at
# ~53 points a year, which also caps the cost of the gap-filling pass.
DAY_BUCKETS_UP_TO_DAYS = 92

# Long enough to absorb a dashboard refresh loop, short enough that an
# admin who just rated something sees it on the next minute.
CACHE_TTL_SECONDS = 60

GRANULARITY_DAY = "day"
GRANULARITY_WEEK = "week"


class InvalidWindow(ValueError):
    """The requested reporting window is not usable."""


def parse_window_days(raw_value):
    """
    Turn the `days` query parameter into a bounded integer.

    Rejecting out-of-range values instead of clamping them keeps the API
    predictable: a client that asks for 10 years gets an error, not a
    silently different number than the one it will print in the UI.
    """

    if raw_value in (None, ""):
        return DEFAULT_WINDOW_DAYS

    try:
        days = int(raw_value)
    except (TypeError, ValueError):
        raise InvalidWindow("days must be an integer.") from None

    if days < 1 or days > MAX_WINDOW_DAYS:
        raise InvalidWindow(
            f"days must be between 1 and {MAX_WINDOW_DAYS}."
        )

    return days


def resolve_window(days):
    """
    Return the inclusive (start, end) datetimes and bucket granularity.

    The window is aligned to calendar days and ends at the end of today,
    not at "now". Two reasons: a row written one millisecond ago must
    still count (a window that ends at `now` drops it), and `days=7`
    must produce exactly seven daily buckets instead of eight.
    """

    now = timezone.localtime()

    end = now.replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )
    start = (now - timedelta(days=days - 1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    granularity = (
        GRANULARITY_DAY
        if days <= DAY_BUCKETS_UP_TO_DAYS
        else GRANULARITY_WEEK
    )

    return start, end, granularity


def _rate(numerator, denominator):
    """
    Percentage, or None when there is nothing to divide by.

    Returning None rather than 0.0 matters: "no one rated anything" and
    "everyone hated it" must not look identical in the UI.
    """

    if not denominator:
        return None

    return round(100.0 * numerator / denominator, 1)


def _as_date(value):
    """TruncDate yields a date, TruncWeek a datetime; normalise both."""

    if isinstance(value, datetime):
        return timezone.localtime(value).date()

    return value


def _bucket_starts(start, end, granularity):
    """
    Every bucket the window touches, in order.

    The database only returns buckets that contain feedback. Without
    this, a quiet week would vanish from the x-axis and the chart would
    connect two distant points as if nothing happened.
    """

    if granularity == GRANULARITY_WEEK:
        cursor = start.date() - timedelta(days=start.weekday())
        step = timedelta(days=7)
    else:
        cursor = start.date()
        step = timedelta(days=1)

    last = end.date()

    while cursor <= last:
        yield cursor
        cursor += step


def _tenant_feedback(tenant_id, start, end, department_id=None):
    """
    Feedback rows for one tenant inside the window.

    `tenant_id` is the denormalised column on the feedback row itself,
    so this filter is served by `feedback_tenant_time_idx` without
    touching `ChatAnswer`. Department is attributed through the answer's
    author, because the question is what belongs to a department: an
    answer cannot be blamed on a department that never asked for it.
    """

    queryset = AnswerFeedback.objects.filter(
        tenant_id=tenant_id,
        created_at__gte=start,
        created_at__lte=end,
    )

    if department_id is not None:
        queryset = queryset.filter(
            answer__user__department_id=department_id,
        )

    return queryset


def _counts():
    """The four conditional counters shared by every aggregate below."""

    return {
        "rated": Count("id"),
        "positive": Count("id", filter=Q(is_positive=True)),
        "negative": Count("id", filter=Q(is_positive=False)),
    }


def _totals(tenant_id, start, end, department_id):
    feedback = _tenant_feedback(tenant_id, start, end, department_id)

    counts = feedback.aggregate(
        **_counts(),
        negative_with_comment=Count(
            "id",
            filter=Q(is_positive=False) & ~Q(user_comment=""),
        ),
    )

    answers = ChatAnswer.objects.filter(
        tenant_id=tenant_id,
        created_at__gte=start,
        created_at__lte=end,
    )

    if department_id is not None:
        answers = answers.filter(user__department_id=department_id)

    # Every stored answer is a potential rating target, including a
    # stream that was aborted halfway: the client already had its
    # `answer_id` and could have rated it. Excluding those rows would
    # let `response_rate` climb above 100%.
    total_answers = answers.count()

    return {
        "answers": total_answers,
        "rated": counts["rated"],
        "positive": counts["positive"],
        "negative": counts["negative"],
        "satisfaction_rate": _rate(counts["positive"], counts["rated"]),
        "response_rate": _rate(counts["rated"], total_answers),
        "positive_share_of_answers": _rate(
            counts["positive"],
            total_answers,
        ),
        "negative_with_comment": counts["negative_with_comment"],
    }


def _trend(tenant_id, start, end, granularity, department_id):
    trunc = TruncWeek if granularity == GRANULARITY_WEEK else TruncDate

    rows = (
        _tenant_feedback(tenant_id, start, end, department_id)
        .annotate(bucket=trunc("created_at"))
        .values("bucket")
        .annotate(**_counts())
        .order_by("bucket")
    )

    by_bucket = {}

    for row in rows:
        by_bucket[_as_date(row["bucket"])] = row

    series = []

    for bucket_start in _bucket_starts(start, end, granularity):
        row = by_bucket.get(bucket_start)

        if row is None:
            series.append(
                {
                    "date": bucket_start.isoformat(),
                    "rated": 0,
                    "positive": 0,
                    "negative": 0,
                    "satisfaction_rate": None,
                }
            )
            continue

        series.append(
            {
                "date": bucket_start.isoformat(),
                "rated": row["rated"],
                "positive": row["positive"],
                "negative": row["negative"],
                "satisfaction_rate": _rate(
                    row["positive"],
                    row["rated"],
                ),
            }
        )

    return series


def _by_department(tenant_id, start, end, department_id):
    rows = (
        _tenant_feedback(tenant_id, start, end, department_id)
        .values(
            "answer__user__department_id",
            "answer__user__department__name",
        )
        .annotate(**_counts())
    )

    stats = {
        row["answer__user__department_id"]: row
        for row in rows
    }

    departments = Department.objects.filter(tenant_id=tenant_id)

    if department_id is not None:
        departments = departments.filter(id=department_id)

    breakdown = []

    for department in departments.order_by("name"):
        row = stats.get(department.id)

        if row is None:
            breakdown.append(
                {
                    "department_id": department.id,
                    "department_name": department.name,
                    "rated": 0,
                    "positive": 0,
                    "negative": 0,
                    "satisfaction_rate": None,
                }
            )
            continue

        breakdown.append(
            {
                "department_id": department.id,
                "department_name": department.name,
                "rated": row["rated"],
                "positive": row["positive"],
                "negative": row["negative"],
                "satisfaction_rate": _rate(row["positive"], row["rated"]),
            }
        )

    return breakdown


def build_quality_metrics(tenant_id, days, department_id=None):
    """
    The uncached computation. Three aggregate queries, no row fetches.

    The alternative — one query per counter, plus one per day — is what
    makes dashboards slow: this is 3 queries whether the window holds 3
    ratings or 300 000.
    """

    start, end, granularity = resolve_window(days)

    return {
        "window": {
            "days": days,
            "date_from": start.date().isoformat(),
            "date_to": end.date().isoformat(),
            "granularity": granularity,
        },
        "totals": _totals(tenant_id, start, end, department_id),
        "trend": _trend(
            tenant_id,
            start,
            end,
            granularity,
            department_id,
        ),
        "by_department": _by_department(
            tenant_id,
            start,
            end,
            department_id,
        ),
    }


def _version_key(tenant_id):
    return f"quality-metrics:v1:{tenant_id}:version"


def _cache_key(tenant_id, version, days, department_id):
    return (
        f"quality-metrics:v1:{tenant_id}:{version}:{days}:"
        f"{department_id if department_id is not None else 'all'}"
    )


def _current_version(tenant_id):
    """
    Read the tenant's cache generation, creating it on first use.

    Django's cache API has no pattern delete, so a new rating cannot
    evict `...:30:all`, `...:7:3` and friends one by one. Bumping a
    generation counter makes every existing key unreachable at once and
    lets them fall out on their own TTL. One `GET`, no scan.
    """

    key = _version_key(tenant_id)

    try:
        version = cache.get(key)
    except Exception:
        logger.warning(
            "Quality metrics cache version read failed.",
            exc_info=True,
        )
        return 0

    if version is None:
        version = 1
        try:
            cache.add(key, version, None)
        except Exception:
            logger.warning(
                "Quality metrics cache version init failed.",
                exc_info=True,
            )

    return version


def get_quality_metrics(tenant_id, days, department_id=None):
    """
    Cached metrics.

    A cache failure must never take the dashboard down, so every cache
    call degrades to "compute it again". The worst case is the query
    cost we would have paid without the cache at all.
    """

    version = _current_version(tenant_id)
    key = _cache_key(tenant_id, version, days, department_id)

    try:
        cached = cache.get(key)
    except Exception:
        logger.warning(
            "Quality metrics cache read failed; computing directly.",
            exc_info=True,
        )
        cached = None

    if cached is not None:
        return cached

    payload = build_quality_metrics(tenant_id, days, department_id)

    try:
        cache.set(key, payload, CACHE_TTL_SECONDS)
    except Exception:
        logger.warning(
            "Quality metrics cache write failed; response is still served.",
            exc_info=True,
        )

    return payload


def invalidate_quality_metrics(tenant_id):
    """
    Retire every cached window for one tenant.

    Called after a rating is stored so the admin sees the new verdict on
    the next refresh instead of up to a minute later. Failure is logged
    and swallowed: a stale dashboard is a nuisance, a 500 on the
    feedback endpoint would lose the user's rating.
    """

    try:
        cache.incr(_version_key(tenant_id))
    except ValueError:
        # Counter missing: nothing was cached yet, so there is nothing
        # to invalidate.
        pass
    except Exception:
        logger.warning(
            "Could not invalidate quality metrics for tenant %s.",
            tenant_id,
            exc_info=True,
        )
