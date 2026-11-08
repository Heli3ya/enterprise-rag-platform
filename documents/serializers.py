import magic

from rest_framework import serializers

from .highlighting import find_highlights
from .links import document_file_url, document_preview_url
from .models import Document, DocumentChunk


MAX_FILE_SIZE = 5 * 1024 * 1024


ALLOWED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class DocumentSerializer(serializers.ModelSerializer):
    file_path = serializers.FileField()
    class Meta:
        model = Document
        fields = [
            "title",
            "file_path",
            "department",
        ]


    def validate_title(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(
                "Title is required."
            )

        return value


    def validate_file_path(self, file):

        if file.size > MAX_FILE_SIZE:
            raise serializers.ValidationError(
                "File size must be less than 5 MB."
            )


        file_type = magic.from_buffer(
            file.read(2048),
            mime=True
        )

        file.seek(0)


        if file_type not in ALLOWED_FILE_TYPES:
            raise serializers.ValidationError(
                "Unsupported file type."
            )

        return file
    
class DocumentStatusSerializer(serializers.ModelSerializer):

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "file_type",
            "status",
            "department",
            "uploaded_by",
            "created_at",
        ]   

class DocumentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "department",
            "status",
            "created_at",
        ]


class ChunkDetailSerializer(serializers.ModelSerializer):
    """
    Everything the UI needs to open a citation: the cited passage,
    the document it belongs to, and a link to the original file.

    The link is a *relative* path so the frontend can resolve it
    against its own API base URL and send the auth header.
    """

    chunk_id = serializers.IntegerField(source="id", read_only=True)
    content = serializers.CharField(read_only=True)
    document_id = serializers.IntegerField(
        source="document.id",
        read_only=True,
    )
    document_title = serializers.CharField(
        source="document.title",
        read_only=True,
    )
    filename = serializers.SerializerMethodField()
    file_type = serializers.CharField(
        source="document.file_type",
        read_only=True,
    )
    department = serializers.CharField(
        source="document.department.name",
        read_only=True,
    )
    department_id = serializers.IntegerField(
        source="document.department.id",
        read_only=True,
    )
    is_public = serializers.BooleanField(
        source="document.is_public",
        read_only=True,
    )
    uploaded_by = serializers.CharField(
        source="document.uploaded_by.username",
        read_only=True,
    )
    created_at = serializers.DateTimeField(
        source="document.created_at",
        read_only=True,
    )
    file_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    highlights = serializers.SerializerMethodField()
    matched_terms = serializers.SerializerMethodField()

    class Meta:
        model = DocumentChunk
        fields = [
            "chunk_id",
            "chunk_index",
            "content",
            "document_id",
            "document_title",
            "filename",
            "file_type",
            "file_url",
            "preview_url",
            "department",
            "department_id",
            "is_public",
            "uploaded_by",
            "created_at",
            "highlights",
            "matched_terms",
        ]

    def get_filename(self, obj):
        # Only the basename is meaningful to a user; the storage
        # path would leak the tenant directory layout.
        return obj.document.file_path.name.rsplit("/", 1)[-1]

    def get_file_url(self, obj):
        return document_file_url(obj.document_id)

    def get_preview_url(self, obj):
        return document_preview_url(obj.document_id)

    def _query(self):
        request = self.context.get("request")

        if request is None:
            return ""

        return request.query_params.get("q", "")

    def _highlight_data(self, obj):
        # Both fields need the same scan; compute it once per object.
        cached = getattr(self, "_highlight_result", None)

        if cached is None or cached[0] != obj.pk:
            cached = (obj.pk, find_highlights(obj.content, self._query()))
            self._highlight_result = cached

        return cached[1]

    def get_highlights(self, obj):
        ranges, _ = self._highlight_data(obj)

        return ranges

    def get_matched_terms(self, obj):
        _, terms = self._highlight_data(obj)

        return terms
