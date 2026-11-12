"""
Cold-start guide for a brand-new department.

A department created five minutes ago has no documents, so every
question would end in "nothing found" — a dead end for the user and a
support ticket for the admin. To avoid that, each department is seeded
with one small, self-describing document that answers the questions a
new user actually has on day one: how to upload, which formats work,
what the statuses mean, and why answers carry citations.

Design notes
------------
* The guide is a real `Document`, not a special-cased answer path. It
  goes through the normal chunk -> embed -> search pipeline, so there is
  no second code path to keep in sync, and it disappears from the way as
  soon as real content arrives.
* Chunks are written synchronously (pure Python, a few milliseconds) but
  embeddings are enqueued after commit. If the broker is down the guide
  is still found by the keyword half of hybrid search, so the cold-start
  promise survives a partial outage.
* `is_system=True` keeps the guide out of "my documents" counts, so the
  dashboard can still show its empty state until a human uploads a file.
"""

import logging
import re

from django.core.files.base import ContentFile
from django.db import transaction

from .chunking import save_document_chunks
from .models import Document

logger = logging.getLogger(__name__)

ONBOARDING_TITLE_PREFIX = "راهنمای شروع به کار دپارتمان"

# Same window the upload pipeline uses, so the guide chunks look exactly
# like the chunks of a real document.
ONBOARDING_CHUNK_SIZE = 400
ONBOARDING_OVERLAP_PERCENT = 10


def onboarding_title(department):
    """Human readable, greppable, and unique per department."""

    return f"{ONBOARDING_TITLE_PREFIX} «{department.name}»"[:255]


def build_onboarding_text(department):
    """
    The guide itself.

    Written in Persian because that is the language the platform's
    documents and questions are in; the wording deliberately repeats the
    terms a new user types (بارگذاری، آپلود، سند، جستجو، PDF، استناد) so
    both halves of hybrid search can hit it.
    """

    department_name = department.name
    organization = getattr(department.tenant, "name", None) or "سازمان شما"

    return f"""
راهنمای شروع به کار دپارتمان «{department_name}»

این سند به صورت خودکار توسط پلتفرم برای دپارتمان «{department_name}» در {organization} ساخته شده است. هدف آن پاسخ دادن به پرسش‌های پایه درباره نحوه استفاده از پلتفرم است، تا زمانی که اسناد واقعی دپارتمان بارگذاری شوند.

۱. وضعیت این دپارتمان
در حال حاضر هیچ سند اختصاصی دیگری برای این دپارتمان بارگذاری نشده است. تا زمانی که اولین سند اضافه شود، پاسخ‌های دستیار فقط بر پایه همین راهنما ساخته می‌شوند. اگر پرسشی درباره موضوعی خارج از این راهنما بپرسید، سیستم به جای حدس زدن صریحاً اعلام می‌کند که سندی برای آن موضوع وجود ندارد.

۲. چگونه اولین سند را بارگذاری کنم؟
در صفحه اصلی، بخش «بارگذاری سند» را باز کنید، فایل را انتخاب یا داخل کادر رها کنید، عنوان سند و دپارتمان مقصد را مشخص کنید و دکمه بارگذاری را بزنید. حداکثر حجم هر فایل پنج مگابایت است.

۳. چه فرمت‌هایی پشتیبانی می‌شود؟
فرمت‌های PDF، DOC، DOCX و TXT پشتیبانی می‌شوند. فایل‌های اسکن‌شده که متن قابل استخراج ندارند نتیجه مناسبی نمی‌دهند، چون متن آن‌ها استخراج نمی‌شود.

۴. پس از بارگذاری چه اتفاقی می‌افتد؟
سند ابتدا در وضعیت Pending قرار می‌گیرد، سپس متن آن استخراج و به قطعه‌های کوچک تقسیم می‌شود. برای هر قطعه یک بردار معنایی ساخته می‌شود و پس از پایان این مراحل وضعیت سند به Indexed تغییر می‌کند. تا زمانی که سند به Indexed نرسیده باشد، در پاسخ‌دهی مشارکت کامل ندارد.

۵. جستجو چگونه کار می‌کند؟
جستجو ترکیبی است: شباهت معنایی و جستجوی کلیدواژه‌ای با هم ترکیب می‌شوند و سپس یک مدل بازرتبه‌بندی نتایج را بر اساس میزان ارتباط با پرسش مرتب می‌کند. به همین دلیل پرسش را کامل و مشخص بنویسید؛ برای نمونه «مراحل بارگذاری سند PDF چیست» نتیجه بهتری از «سند» می‌دهد.

۶. چرا پاسخ‌ها استناد دارند؟
هر جمله‌ای که از یک سند گرفته شود با شناسه قطعه در داخل قلاب مشخص می‌شود. با کلیک روی هر استناد، متن اصلی سند و بخشی که پاسخ از آن ساخته شده نمایش داده می‌شود. اگر جمله‌ای استناد نداشته باشد، یعنی از اسناد استخراج نشده است.

۷. اگر پیام «سندی یافت نشد» گرفتم چه کنم؟
این پیام یعنی در دپارتمان شما سندی وجود ندارد که به آن پرسش مربوط باشد. دو راه دارید: پرسش را با کلمات دیگر یا کلی‌تر بپرسید، یا سند مرتبط را بارگذاری کنید. در این حالت سیستم برای صرفه‌جویی در هزینه، مدل زبانی را فراخوانی نمی‌کند و پاسخ حدسی نمی‌سازد.

۸. حریم خصوصی و دسترسی
هر سند به یک دپارتمان تعلق دارد و فقط اعضای همان دپارتمان و مدیر سازمان می‌توانند آن را در جستجو ببینند. اسناد دپارتمان‌های دیگر و سازمان‌های دیگر هرگز در نتایج شما ظاهر نمی‌شوند.

۹. پرسش‌های رایج
چطور سند آپلود کنم؟ بخش دوم همین راهنما را ببینید.
چه فرمت‌هایی پشتیبانی می‌شود؟ PDF، DOC، DOCX و TXT.
چرا سند من در جستجو نیست؟ وضعیت سند باید Indexed باشد؛ چند دقیقه بعد دوباره بررسی کنید.
آیا می‌توانم سند را حذف کنم؟ بله، از فهرست اسناد بارگذاری‌شده و برای سندهایی که خودتان بارگذاری کرده‌اید یا به عنوان مدیر سازمان.
چطور پرسش بهتری بپرسم؟ موضوع، بازه زمانی و نام سند را در پرسش بیاورید.
""".strip()


def _safe_filename(department):
    """
    ASCII-only storage name.

    The original name is user-controlled and Persian; keeping it out of
    the storage path avoids encoding problems on Windows hosts while the
    readable title stays in the database.
    """

    slug = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        department.name or "",
    ).strip("-").lower()

    return f"onboarding-{department.id}-{slug or 'department'}.txt"


def resolve_guide_author(department, preferred=None):
    """
    Decide who the generated document is attributed to.

    The API passes the admin who created the department. Departments
    created from a shell, a fixture or the Django admin have no such
    hint, so the tenant's first active admin (and then any active user)
    is used instead of skipping the guide altogether. Returns None when
    the tenant has no user at all, which is the only case where the
    guide is legitimately skipped.
    """

    if preferred is not None and getattr(preferred, "pk", None):
        return preferred

    if department.tenant_id is None:
        return None

    # Imported lazily: the user model depends on this app's models, and
    # onboarding is imported from a signal during app loading.
    from django.contrib.auth import get_user_model

    users = get_user_model().objects.filter(
        tenant_id=department.tenant_id,
        is_active=True,
    )

    return (
        users.filter(role="Admin").order_by("id").first()
        or users.order_by("id").first()
    )


def _enqueue_embeddings(document_id, chunk_ids):
    """
    Hand the chunks to Celery, and never let a broker outage matter.

    Without embeddings the guide is still reachable through keyword
    search, which is enough to answer "how do I upload a file?". So a
    failed enqueue is logged and swallowed instead of rolling back a
    department creation.

    This is a `warning`, not an `exception`: the outcome is explicitly
    tolerated and the document is still usable, so it must not open an
    error-level issue in Sentry. Same reasoning as the optional
    reranker in `api.services.hybrid_search`.
    """

    try:
        from .tasks import EMBEDDING_BATCH_SIZE, generate_embedding_batch

        for start in range(0, len(chunk_ids), EMBEDDING_BATCH_SIZE):
            generate_embedding_batch.delay(
                document_id,
                chunk_ids[start:start + EMBEDDING_BATCH_SIZE],
            )
    except Exception as exc:
        logger.warning(
            "Could not enqueue onboarding embeddings for document %s "
            "(%s); the guide stays reachable through keyword search.",
            document_id,
            exc,
        )


def ensure_onboarding_document(department, created_by=None):
    """
    Create the guide for `department` if it does not have one yet.

    Idempotent by design: it is called from the department signal, from
    the backfill command, and from tests, and creating a second guide
    would only duplicate chunks in the search index.

    Returns the created Document, or None when there is nothing to do
    (no tenant, already present, or no user to attribute it to).
    """

    if department is None or department.tenant_id is None:
        return None

    if Document.objects.filter(
        department=department,
        is_system=True,
    ).exists():
        return None

    if created_by is None:
        return None

    text = build_onboarding_text(department)

    document = Document(
        tenant_id=department.tenant_id,
        title=onboarding_title(department),
        department=department,
        uploaded_by=created_by,
        file_type="text/plain",
        status="Processing",
        is_public=False,
        is_system=True,
        file_size=0,
    )

    payload = text.encode("utf-8")

    document.file_path.save(
        _safe_filename(department),
        ContentFile(payload),
        save=False,
    )

    # `size` needs the file on storage; fall back to the byte length if
    # a remote backend cannot report it.
    try:
        document.file_size = document.file_path.size
    except Exception:
        document.file_size = len(payload)

    document.save()

    chunk_objects = save_document_chunks(
        document,
        text,
        chunk_size=ONBOARDING_CHUNK_SIZE,
        overlap_percent=ONBOARDING_OVERLAP_PERCENT,
    )

    if not chunk_objects:
        document.status = "Failed"
        document.save(update_fields=["status"])

        logger.warning(
            "Onboarding guide for department %s produced no chunks.",
            department.pk,
        )

        return document

    chunk_ids = [chunk.id for chunk in chunk_objects]

    # After commit: the worker must never see a chunk that the
    # transaction later rolls back.
    transaction.on_commit(
        lambda: _enqueue_embeddings(document.id, chunk_ids)
    )

    logger.info(
        "Created onboarding guide %s for department %s (%s chunks).",
        document.id,
        department.pk,
        len(chunk_ids),
    )

    return document
