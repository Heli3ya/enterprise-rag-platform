
import magic

from django.db import transaction
from django.utils.decorators import method_decorator

from django_ratelimit.decorators import ratelimit

from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema

from api.audit import create_audit_log
from api.permissions import IsDepartmentMember

from .models import Document
from .serializers import (
    DocumentSerializer,
    DocumentStatusSerializer,
    DocumentListSerializer,
)
from .tasks import process_document


@extend_schema(
    request=DocumentSerializer,
    responses=DocumentSerializer,
)
class DocumentUploadView(generics.ListCreateAPIView):
    permission_classes = [IsDepartmentMember]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return (
            Document.objects
            .filter(uploaded_by=self.request.user)
            .select_related("department")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.request.method == "GET":
            return DocumentListSerializer

        return DocumentSerializer

    def perform_create(self, serializer):
        file = self.request.FILES.get("file_path")

        file_type = magic.from_buffer(
            file.read(2048),
            mime=True,
        )

        file.seek(0)

        serializer.save(
            uploaded_by=self.request.user,
            status="Pending",
            file_type=file_type,
            file_size=file.size,
        )

        create_audit_log(
            self.request.user,
            "UPLOAD",
        )

        document = serializer.instance

        transaction.on_commit(
            lambda: process_document.delay(document.id)
        )

    @method_decorator(
        ratelimit(
            key="user",
            rate="10/h",
            method="POST",
            block=False,
        )
    )
    def create(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            raise Throttled(
                detail=(
                    "Upload rate limit exceeded. "
                    "Try again later."
                )
            )

        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        self.perform_create(serializer)

        return Response(
            {
                "document_id": serializer.instance.id,
                "status": serializer.instance.status,
            },
            status=status.HTTP_201_CREATED,
        )


class DocumentStatusView(generics.RetrieveAPIView):
    serializer_class = DocumentStatusSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        document = Document.objects.get(
            id=self.kwargs["pk"]
        )

        if (
            document.department
            != self.request.user.department
        ):
            raise PermissionDenied(
                "You do not have permission to access "
                "this document."
            )

        return document


class DocumentDeleteView(generics.DestroyAPIView):
    queryset = Document.objects.all()
    permission_classes = [IsDepartmentMember]

    def get_object(self):
        document = super().get_object()

        if (
            document.uploaded_by_id != self.request.user.id
            and self.request.user.role != "Admin"
        ):
            raise PermissionDenied(
                "You do not have permission to delete "
                "this document."
            )

        return document

    def perform_destroy(self, instance):
        if instance.file_path:
            instance.file_path.delete(save=False)

        instance.delete()

        create_audit_log(
            self.request.user,
            "DELETE",
        )
