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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class DocumentChunk(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    content = models.TextField()
    chunk_index = models.PositiveIntegerField()

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
            )
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