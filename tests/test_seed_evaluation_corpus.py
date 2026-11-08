"""
The evaluation dataset is only meaningful when the corpus it references
is actually indexed. This covers the seeding command that makes that
true, without needing the AI service: embeddings are stubbed.
"""

import pytest
from django.core.management import call_command

from documents.models import Document, DocumentChunk, Embedding
from tests.factories import AdminFactory


CORPUS_TEXT = (
    "Acme Corporation travel policy. "
    "The daily meal allowance is 45 USD for domestic travel. "
    "The hotel limit is 150 USD per night for domestic travel. "
    "Receipts are required above 25 USD. "
) * 20


@pytest.fixture
def corpus_dir(tmp_path):
    directory = tmp_path / "corpus"
    directory.mkdir()
    (directory / "travel-policy.txt").write_text(CORPUS_TEXT, encoding="utf-8")
    return directory


@pytest.fixture
def stub_embeddings(monkeypatch):
    calls = []

    def fake_generate(texts):
        calls.append(list(texts))
        return [[0.01] * 384 for _ in texts], 384

    monkeypatch.setattr(
        "documents.management.commands.seed_evaluation_corpus.generate_embeddings",
        fake_generate,
    )

    return calls


@pytest.mark.django_db
def test_seed_command_indexes_the_corpus(
    corpus_dir,
    stub_embeddings,
    tmp_path,
    settings,
):
    settings.MEDIA_ROOT = tmp_path / "media"
    admin = AdminFactory()

    call_command(
        "seed_evaluation_corpus",
        tenant=admin.tenant.name,
        department=admin.department.name,
        corpus_dir=str(corpus_dir),
        user=admin.username,
        verbosity=0,
    )

    document = Document.objects.get(title="travel-policy.txt")

    assert document.status == "Indexed"
    assert document.tenant_id == admin.tenant_id
    assert document.department_id == admin.department_id
    assert document.file_type == "text/plain"

    chunks = DocumentChunk.objects.filter(document=document)

    assert chunks.count() >= 1
    assert Embedding.objects.filter(chunk__document=document).count() == (
        chunks.count()
    )
    assert stub_embeddings


@pytest.mark.django_db
def test_seed_command_is_idempotent(
    corpus_dir,
    stub_embeddings,
    tmp_path,
    settings,
):
    settings.MEDIA_ROOT = tmp_path / "media"
    admin = AdminFactory()

    kwargs = {
        "tenant": admin.tenant.name,
        "department": admin.department.name,
        "corpus_dir": str(corpus_dir),
        "user": admin.username,
        "verbosity": 0,
    }

    call_command("seed_evaluation_corpus", **kwargs)
    call_command("seed_evaluation_corpus", **kwargs)

    assert Document.objects.filter(title="travel-policy.txt").count() == 1


@pytest.mark.django_db
def test_seed_command_reset_replaces_the_document(
    corpus_dir,
    stub_embeddings,
    tmp_path,
    settings,
):
    settings.MEDIA_ROOT = tmp_path / "media"
    admin = AdminFactory()

    kwargs = {
        "tenant": admin.tenant.name,
        "department": admin.department.name,
        "corpus_dir": str(corpus_dir),
        "user": admin.username,
        "verbosity": 0,
    }

    call_command("seed_evaluation_corpus", **kwargs)
    first_id = Document.objects.get(title="travel-policy.txt").id

    call_command("seed_evaluation_corpus", reset=True, **kwargs)

    documents = Document.objects.filter(title="travel-policy.txt")

    assert documents.count() == 1
    assert documents.first().id != first_id
    assert documents.first().status == "Indexed"
