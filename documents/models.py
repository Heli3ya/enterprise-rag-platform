from django.db import models
from django.conf import settings
from pgvector.django import VectorField
from departments.models import Department


class Document(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Indexed', 'Indexed'),
        ('Failed', 'Failed'),
    )

    title = models.CharField(max_length=255)

    file_path = models.FileField(upload_to='documents/')

    file_type = models.CharField(max_length=20)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending'
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class DocumentChunk(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='chunks'
    )

    content = models.TextField()

    chunk_index = models.PositiveIntegerField()

    class Meta:
        ordering = ['chunk_index']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'chunk_index'],
                name='unique_document_chunk_index'
            )
        ]

    def __str__(self):
        return f'{self.document.title} - Chunk {self.chunk_index}'


class Embedding(models.Model):
    chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name='embeddings'
    )

    embedding_vector = VectorField(dimensions=384)

    model_name = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.chunk} - {self.model_name}'