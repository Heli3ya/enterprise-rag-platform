import magic

from rest_framework import serializers
from .models import Document


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