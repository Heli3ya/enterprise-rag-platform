"""
Sub-task 1 — the model: `version` and `parent_document`.

What is being pinned down here is the shape of a version chain and the
two invariants the database enforces on its own: a parent can have only
one child with a given number, and a version number starts at 1.
"""

import pytest
from django.db import IntegrityError, transaction

from documents.models import Document, DocumentChunk, Embedding
from documents.versioning import (
    ARCHIVED_STATUS,
    archive_document,
    delete_chain,
    is_current,
    latest_version,
    next_version_number,
    version_chain,
)
from tests.factories import DocumentChunkFactory, DocumentFactory


def make_version(parent, **overrides):
    """A document that replaces `parent`, wired the way the API wires it."""

    values = {
        "title": parent.title,
        "uploaded_by": parent.uploaded_by,
        "department": parent.department,
        "tenant": parent.tenant,
        "version": parent.version + 1,
        "parent_document": parent,
    }
    values.update(overrides)

    return Document.objects.create(**values)


def add_embedding(chunk):
    return Embedding.objects.create(
        chunk=chunk,
        embedding_vector=[0.0] * 384,
        model_name="test-embedding-model",
    )


@pytest.mark.django_db
def test_a_new_document_starts_at_version_one_with_no_parent():
    document = DocumentFactory()

    assert document.version == 1
    assert document.parent_document_id is None
    assert document.archived_at is None
    assert document.is_archived is False


@pytest.mark.django_db
def test_a_child_points_at_its_parent_and_carries_the_next_version():
    first = DocumentFactory()

    second = make_version(first)

    assert second.version == 2
    assert second.parent_document_id == first.id
    assert second.tenant_id == first.tenant_id
    assert second.department_id == first.department_id
    assert next_version_number(first) == 2
    assert next_version_number(second) == 3


@pytest.mark.django_db
def test_a_parent_cannot_have_two_children_with_the_same_version():
    first = DocumentFactory()
    make_version(first)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_version(first)


@pytest.mark.django_db
def test_a_version_number_must_be_at_least_one():
    user = DocumentFactory().uploaded_by

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Document.objects.create(
                title="Impossible version",
                uploaded_by=user,
                department=user.department,
                tenant=user.tenant,
                version=0,
            )


@pytest.mark.django_db
def test_two_separate_documents_can_both_be_version_one():
    # NULL parents are distinct in Postgres, so the uniqueness rule does
    # not accidentally allow only one document per database.
    first = DocumentFactory()
    second = DocumentFactory()

    assert first.version == 1
    assert second.version == 1
    assert first.parent_document_id is None
    assert second.parent_document_id is None


@pytest.mark.django_db
def test_the_string_representation_shows_the_version_only_after_one():
    first = DocumentFactory(title="Travel policy")
    second = make_version(first)

    assert str(first) == "Travel policy"
    assert str(second) == "Travel policy (v2)"


@pytest.mark.django_db
def test_the_chain_is_returned_oldest_first_from_any_member():
    first = DocumentFactory()
    second = make_version(first)
    third = make_version(second)

    assert [item.id for item in version_chain(first)] == [
        first.id,
        second.id,
        third.id,
    ]
    assert [item.id for item in version_chain(second)] == [
        first.id,
        second.id,
        third.id,
    ]


@pytest.mark.django_db
def test_only_the_newest_version_is_current():
    first = DocumentFactory()
    second = make_version(first)

    assert is_current(first) is False
    assert is_current(second) is True
    assert latest_version(first).id == second.id


@pytest.mark.django_db
def test_an_archived_newest_version_is_not_current():
    first = DocumentFactory()
    second = make_version(first)

    archive_document(second)

    assert is_current(second) is False
    assert latest_version(first).id == second.id


@pytest.mark.django_db
def test_archiving_drops_vectors_but_keeps_the_text():
    first = DocumentFactory()
    chunk_a = DocumentChunkFactory(document=first, chunk_index=0)
    chunk_b = DocumentChunkFactory(document=first, chunk_index=1)
    add_embedding(chunk_a)
    add_embedding(chunk_b)

    removed = archive_document(first)

    first.refresh_from_db()

    assert first.status == ARCHIVED_STATUS
    assert first.archived_at is not None
    assert removed == 2
    assert Embedding.objects.count() == 0
    # The text stays: citations issued against v1 must still resolve.
    assert DocumentChunk.objects.filter(document=first).count() == 2


@pytest.mark.django_db
def test_deleting_any_member_removes_the_whole_chain():
    first = DocumentFactory()
    second = make_version(first)
    third = make_version(second)

    removed = delete_chain(second)

    assert sorted(removed) == sorted([first.id, second.id, third.id])
    assert Document.objects.count() == 0
