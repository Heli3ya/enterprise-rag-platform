"""
Sub-task 1 — the cleanup worker itself.

`documents.cleanup_superseded_document` is the only thing that removes
a superseded version from the index. Everything here is about the
worker's contract rather than about search: what it touches, what it
refuses to touch, and what happens when Celery delivers the same
message twice.
"""

import pytest
from django.utils import timezone

from documents.cleanup import purge_version
from documents.models import Document, DocumentChunk, Embedding
from documents.tasks import cleanup_superseded_document
from tests.factories import (
    DocumentChunkFactory,
    DocumentFactory,
    UserFactory,
)


def build_version(
    user,
    title,
    version,
    parent=None,
    status="Indexed",
    content="Receipts must be submitted within 30 days.",
):
    document = DocumentFactory(
        uploaded_by=user,
        department=user.department,
        tenant=user.tenant,
        title=title,
        status=status,
        version=version,
        parent_document=parent,
    )
    chunk = DocumentChunkFactory(
        document=document,
        chunk_index=0,
        content=content,
    )
    Embedding.objects.create(
        chunk=chunk,
        embedding_vector=[0.0] * 384,
        model_name="test-embedding-model",
    )

    return document, chunk


@pytest.mark.django_db
def test_the_worker_purges_the_version_it_replaced():
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    result = cleanup_superseded_document.run(new.id)

    old_chunk.refresh_from_db()
    old.refresh_from_db()

    assert result["versions_purged"] == 1
    assert result["chunks_tombstoned"] == 1
    assert result["embeddings_deleted"] == 1
    assert old_chunk.is_active is False
    assert old.purged_at is not None
    assert Embedding.objects.filter(chunk=old_chunk).count() == 0


@pytest.mark.django_db
def test_the_worker_keeps_the_text_of_the_old_version():
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)

    # Tombstoned, not deleted: an answer delivered last month still
    # opens the passage the user actually read.
    assert DocumentChunk.objects.filter(id=old_chunk.id).exists()
    assert (
        DocumentChunk.objects.get(id=old_chunk.id).content
        == "Receipts must be submitted within 30 days."
    )


@pytest.mark.django_db
def test_the_worker_leaves_the_current_version_alone():
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, new_chunk = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)

    new_chunk.refresh_from_db()
    new.refresh_from_db()

    assert new_chunk.is_active is True
    assert new.purged_at is None
    assert Embedding.objects.filter(chunk=new_chunk).count() == 1


@pytest.mark.django_db
def test_a_second_run_is_a_no_op():
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    first = cleanup_superseded_document.run(new.id)
    second = cleanup_superseded_document.run(new.id)

    assert first["chunks_tombstoned"] == 1
    assert second["chunks_tombstoned"] == 0
    assert second["embeddings_deleted"] == 0
    assert second["results"][0]["already_purged"] is True


@pytest.mark.django_db
def test_the_purge_timestamp_is_not_moved_by_a_retry():
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)
    old.refresh_from_db()
    first_timestamp = old.purged_at

    cleanup_superseded_document.run(new.id)
    old.refresh_from_db()

    # "Since when is this version out of the index?" has one answer,
    # and a redelivered message must not rewrite it.
    assert old.purged_at == first_timestamp


@pytest.mark.django_db
def test_the_worker_walks_the_whole_chain():
    user = UserFactory()
    first, first_chunk = build_version(
        user, "Travel policy", 1, status="Archived"
    )
    second, second_chunk = build_version(
        user, "Travel policy", 2, parent=first, status="Archived"
    )
    third, third_chunk = build_version(
        user, "Travel policy", 3, parent=second
    )

    result = cleanup_superseded_document.run(third.id)

    first_chunk.refresh_from_db()
    second_chunk.refresh_from_db()
    third_chunk.refresh_from_db()

    assert result["versions_purged"] == 2
    assert first_chunk.is_active is False
    assert second_chunk.is_active is False
    # The version the user can actually get an answer from survives.
    assert third_chunk.is_active is True


@pytest.mark.django_db
def test_the_worker_repairs_a_purge_that_was_lost():
    """
    v2 indexed but its cleanup never ran, then v3 is uploaded.

    The worker for v3 must cover v1 as well, not only its own parent —
    otherwise a lost message leaves a version in the index forever.
    """

    user = UserFactory()
    first, first_chunk = build_version(
        user, "Travel policy", 1, status="Archived"
    )
    second, second_chunk = build_version(
        user, "Travel policy", 2, parent=first, status="Archived"
    )
    third, _ = build_version(user, "Travel policy", 3, parent=second)

    cleanup_superseded_document.run(third.id)

    first_chunk.refresh_from_db()
    second_chunk.refresh_from_db()

    assert first_chunk.is_active is False
    assert second_chunk.is_active is False


@pytest.mark.django_db
def test_the_worker_skips_a_document_that_is_not_indexed():
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(
        user, "Travel policy", 2, parent=old, status="Pending"
    )

    result = cleanup_superseded_document.run(new.id)

    old_chunk.refresh_from_db()

    # The replacement is not usable yet, so the old version must stay
    # where it is: it is still the best answer the department has.
    assert result["skipped"] == "not_indexed"
    assert old_chunk.is_active is True
    assert Embedding.objects.filter(chunk=old_chunk).count() == 1


@pytest.mark.django_db
def test_the_worker_skips_a_document_that_no_longer_exists():
    result = cleanup_superseded_document.run(999_999)

    assert result["skipped"] == "missing"


@pytest.mark.django_db
def test_the_worker_does_not_touch_another_document():
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)
    other, other_chunk = build_version(
        user, "Leave policy", 1, status="Indexed"
    )

    cleanup_superseded_document.run(new.id)

    other_chunk.refresh_from_db()

    assert other_chunk.is_active is True
    assert Embedding.objects.filter(chunk=other_chunk).count() == 1


@pytest.mark.django_db
def test_the_worker_ignores_a_version_that_was_restored():
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    # Someone put the old version back in service between the trigger
    # and this run. Its text is live again, so it keeps its index.
    Document.objects.filter(id=old.id).update(
        status="Indexed",
        archived_at=None,
    )

    result = cleanup_superseded_document.run(new.id)

    old_chunk.refresh_from_db()

    assert result["versions_purged"] == 0
    assert old_chunk.is_active is True
    assert Embedding.objects.filter(chunk=old_chunk).count() == 1


@pytest.mark.django_db
def test_purging_a_restored_version_is_refused():
    """
    The race the walk cannot see: the version is archived when the
    chain is read and restored before the row lock is taken.
    """

    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")

    Document.objects.filter(id=old.id).update(
        status="Indexed",
        archived_at=None,
    )

    result = purge_version(Document.objects.get(id=old.id))

    old_chunk.refresh_from_db()

    assert result["skipped"] == "not_archived"
    assert old_chunk.is_active is True
    assert Embedding.objects.filter(chunk=old_chunk).count() == 1


@pytest.mark.django_db
def test_the_worker_deletes_a_vector_written_after_the_first_purge():
    """
    The interleaving the tombstone alone cannot cover: a batch that was
    already running when the purge happened finishes afterwards and
    writes a vector for a tombstoned chunk. A redelivery of the cleanup
    message is what removes it.
    """

    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)

    Embedding.objects.create(
        chunk=old_chunk,
        embedding_vector=[0.0] * 384,
        model_name="test-embedding-model",
    )

    result = cleanup_superseded_document.run(new.id)

    assert result["embeddings_deleted"] == 1
    assert Embedding.objects.filter(chunk=old_chunk).count() == 0


@pytest.mark.django_db
def test_the_worker_marks_when_it_purged():
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    before = timezone.now()
    cleanup_superseded_document.run(new.id)
    after = timezone.now()

    old.refresh_from_db()
    old_chunk.refresh_from_db()

    assert before <= old.purged_at <= after
    assert before <= old_chunk.purged_at <= after
