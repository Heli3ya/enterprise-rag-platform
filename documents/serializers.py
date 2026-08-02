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

    class Meta:
        model = Document
        fields = '__all__'

    def validate_file_path(self, file):

        # بررسی حجم فایل
        if file.size > MAX_FILE_SIZE:
            raise serializers.ValidationError(
                "File size must be less than 5 MB."
            )

        # تشخیص واقعی نوع فایل
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