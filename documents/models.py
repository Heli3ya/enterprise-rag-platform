from django.db import models
from django.conf import settings
from pgvector.django import VectorField, HnswIndex
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from departments.models import Department


def tenant_document_upload_to(instance, filename):
    """
    Store each document inside its tenant-specific directory.
    """

    if instance.tenant_id is None:
        raise ValueError(
            "Cannot store a document without an assigned tenant."
        )

    # Keep only the filename, not any user-supplied directory path.
    safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1]

    if not safe_filename:
        raise ValueError("Invalid document filename.")

    return (
        f"documents/tenant_{instance.tenant_id}/"
        f"{safe_filename}"
    )


class Document(models.Model):
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents",
    )

    STATUS_CHOICES = (
        ("Pending", "Pending"),
        ("Processing", "Processing"),
        ("Indexed", "Indexed"),
        ("Failed", "Failed"),
        # A version that a newer upload has replaced. Its text stays in
        # the database so old citations still resolve, but its vectors
        # are dropped: the search engine must never cite a superseded
        # procedure as if it were current.
        ("Archived", "Archived"),
    )

    title = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    file_path = models.FileField(
        upload_to=tenant_document_upload_to
    )
    file_type = models.CharField(max_length=20)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
    )

    is_public = models.BooleanField(default=False)

    # True for documents the platform writes itself (today: the
    # department onboarding guide). They are chunked and searchable like
    # any other document, but they are not user content: the dashboard
    # keeps showing "no documents yet" until a real file is uploaded, and
    # the analytics totals ignore them.
    is_system = models.BooleanField(default=False)

    # Version chain. A document uploaded for the first time is v1 with
    # no parent; a replacement points at the version it replaces and
    # carries that version's number plus one. The link is to the
    # *previous* version, not to the root, so the chain records the
    # order in which the document changed.
    version = models.PositiveIntegerField(default=1)

    parent_document = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_versions",
    )

    # When a newer version retired this row. `status` answers "is it
    # searchable?", this answers "since when?" — the question an audit
    # asks and the status field cannot.
    archived_at = models.DateTimeField(null=True, blank=True)

    # When the cleanup worker removed this version's searchable
    # footprint: chunks tombstoned, vectors deleted. NULL means "not
    # purged yet". It doubles as the worker's idempotency marker, so a
    # retried task can tell "already done" from "nothing to do".
    purged_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Two concurrent uploads both computing "v2" for the same
            # parent would fork the chain. The lock in the view makes
            # that rare; this makes it impossible.
            models.UniqueConstraint(
                fields=["parent_document", "version"],
                name="unique_document_version_per_parent",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="document_version_at_least_one",
            ),
        ]
        indexes = [
            # The document list filters by tenant and hides archived
            # rows on every page load.
            models.Index(
                fields=["tenant", "status"],
                name="document_tenant_status_idx",
            ),
        ]

    def __str__(self):
        if self.version and self.version > 1:
            return f"{self.title} (v{self.version})"

        return self.title

    @property
    def is_archived(self):
        return self.status == "Archived"


class DocumentChunk(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    content = models.TextField()
    chunk_index = models.PositiveIntegerField()

    # A superseded version keeps its text so citations issued against
    # it still resolve, but its chunks are tombstoned so no retrieval
    # path can return them. Deleting the row instead would blank the
    # sources of answers that were already delivered to a user.
    is_active = models.BooleanField(default=True)

    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="unique_document_chunk_index",
            )
        ]
        indexes = [
            GinIndex(
                SearchVector("content", config="simple"),
                name="documentchunk_content_fts_idx",
            ),
            # Partial: every retrieval query asks for the live chunks of
            # a document, and tombstoned rows are never read. Keeping
            # them out of the index keeps it small as revisions pile up.
            models.Index(
                fields=["document"],
                name="documentchunk_active_idx",
                condition=models.Q(is_active=True),
            ),
        ]

    def __str__(self):
        return f"{self.document.title} - Chunk {self.chunk_index}"


class Embedding(models.Model):
    chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="embeddings",
    )

    embedding_vector = VectorField(dimensions=384)
    model_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            HnswIndex(
                name="embedding_vector_hnsw_idx",
                fields=["embedding_vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    def __str__(self):
        return f"{self.chunk} - {self.model_name}"


class SearchQuery(models.Model):
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="search_queries",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="search_queries",
    )

    query_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["-created_at"],
                name="searchquery_created_idx",
            ),
        ]

    def __str__(self):
        return self.query_text


class QueryResult(models.Model):
    query = models.ForeignKey(
        SearchQuery,
        on_delete=models.CASCADE,
        related_name="results",
    )

    chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="query_results",
    )

    relevance_score = models.FloatField()

    def __str__(self):
        return f"{self.query.query_text} - Chunk {self.chunk_id}"