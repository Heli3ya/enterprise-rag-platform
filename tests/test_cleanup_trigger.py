"""
Sub-task 2 — the purge is wired to the *successful* processing of the
replacement, not to the upload.

The distinction is the whole point of the sub-task. Archiving happens at
upload time; purging must not, or a failed extraction would leave the
department with no searchable text at all. These tests pin the trigger
to the moment the new version reaches `Indexed`, and pin the purge to
the rows that version replaced.
"""

from unittest.mock import patch

import pytest

from api.services import build_citations
from documents.models import DocumentChunk, Embedding
from documents.tasks import (
    cleanup_superseded_document,
    generate_embedding_batch,
)
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
    with_embedding=True,
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

    if with_embedding:
        Embedding.objects.create(
            chunk=chunk,
            embedding_vector=[0.0] * 384,
            model_name="test-embedding-model",
        )

    return document, chunk


def fake_embeddings(texts):
    return [[0.0] * 384 for _ in texts], 384


@pytest.mark.django_db
def test_indexing_the_new_version_queues_the_cleanup(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, new_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Processing",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks(execute=True):
            generate_embedding_batch.run(new.id, [new_chunk.id])

    delay.assert_called_once_with(new.id)


@pytest.mark.django_db
def test_a_first_upload_queues_no_cleanup(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    document, chunk = build_version(
        user,
        "Travel policy",
        1,
        status="Processing",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks(execute=True):
            generate_embedding_batch.run(document.id, [chunk.id])

    # Nothing was replaced, so there is nothing to purge. Enqueuing here
    # would put one no-op task in the queue per document ever uploaded.
    delay.assert_not_called()


@pytest.mark.django_db
def test_the_cleanup_is_queued_after_the_commit_not_before(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, new_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Processing",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks() as callbacks:
            generate_embedding_batch.run(new.id, [new_chunk.id])

            # The worker must not be able to read a row that is still
            # "Processing" and skip the purge as a no-op.
            delay.assert_not_called()

        for callback in callbacks:
            callback()

    delay.assert_called_once_with(new.id)


@pytest.mark.django_db
def test_an_incomplete_batch_queues_no_cleanup(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, first_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Processing",
        with_embedding=False,
    )
    DocumentChunkFactory(
        document=new,
        chunk_index=1,
        content="The second half of the new version.",
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks(execute=True):
            generate_embedding_batch.run(new.id, [first_chunk.id])

    new.refresh_from_db()

    assert new.status == "Processing"
    delay.assert_not_called()


@pytest.mark.django_db
def test_a_failed_batch_queues_no_cleanup(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, old_chunk = build_version(user, "Travel policy", 1, status="Archived")
    new, new_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Processing",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        return_value=([], 384),
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(ValueError):
                generate_embedding_batch.run(new.id, [new_chunk.id])

    old_chunk.refresh_from_db()

    delay.assert_not_called()
    # The old version is still the best answer available.
    assert old_chunk.is_active is True


@pytest.mark.django_db
def test_an_archived_document_queues_no_cleanup(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, _ = build_version(user, "Travel policy", 1, status="Archived")
    new, new_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Archived",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ) as delay:
        with django_capture_on_commit_callbacks(execute=True):
            generate_embedding_batch.run(new.id, [new_chunk.id])

    delay.assert_not_called()


@pytest.mark.django_db
def test_the_old_version_is_purged_once_the_new_one_is_indexed(
    django_capture_on_commit_callbacks,
):
    user = UserFactory()
    old, old_chunk = build_version(
        user, "Travel policy", 1, status="Archived"
    )
    new, new_chunk = build_version(
        user,
        "Travel policy",
        2,
        parent=old,
        status="Processing",
        with_embedding=False,
    )

    with patch(
        "documents.tasks.generate_embeddings",
        side_effect=fake_embeddings,
    ), patch(
        "documents.tasks.cleanup_superseded_document.delay",
    ):
        with django_capture_on_commit_callbacks(execute=True):
            generate_embedding_batch.run(new.id, [new_chunk.id])

    new.refresh_from_db()
    assert new.status == "Indexed"

    cleanup_superseded_document.run(new.id)

    old_chunk.refresh_from_db()
    new_chunk.refresh_from_db()

    assert old_chunk.is_active is False
    assert Embedding.objects.filter(chunk=old_chunk).count() == 0
    assert new_chunk.is_active is True


@pytest.mark.django_db
def test_the_old_citations_still_resolve_after_the_purge():
    user = UserFactory()
    old, old_chunk = build_version(
        user, "Travel policy", 1, status="Archived"
    )
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)

    citations = build_citations([old_chunk.id], user=user)

    # Purged from the index is not the same as erased from history.
    assert len(citations) == 1
    assert citations[0]["document_id"] == old.id


@pytest.mark.django_db
def test_the_purge_does_not_delete_the_chunk_rows():
    user = UserFactory()
    old, old_chunk = build_version(
        user, "Travel policy", 1, status="Archived"
    )
    new, _ = build_version(user, "Travel policy", 2, parent=old)

    cleanup_superseded_document.run(new.id)

    assert DocumentChunk.objects.filter(id=old_chunk.id).exists()
    assert DocumentChunk.objects.get(id=old_chunk.id).is_active is False
