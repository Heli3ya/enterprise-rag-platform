
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
        user = self.request.user

        if user.tenant_id is None:
            return Document.objects.none()

        return (
            Document.objects
            .filter(tenant_id=user.tenant_id)
            .select_related("department")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.request.method == "GET":
            return DocumentListSerializer
        return DocumentSerializer

    def perform_create(self, serializer):
        user = self.request.user
        department = serializer.validated_data["department"]
        file = self.request.FILES.get("file_path")

        if user.tenant_id is None:
            raise PermissionDenied(
                "Your account is not assigned to an organization."
            )

        if department.tenant_id != user.tenant_id:
            raise PermissionDenied(
                "You cannot upload documents to another organization."
            )

        if user.department_id != department.id and user.role != "Admin":
            raise PermissionDenied(
                "You cannot upload documents to this department."
            )

        file_type = magic.from_buffer(file.read(2048), mime=True)
        file.seek(0)

        document = serializer.save(
            tenant_id=user.tenant_id,
            uploaded_by=user,
            status="Pending",
            file_type=file_type,
            file_size=file.size,
        )

        create_audit_log(user, "UPLOAD")

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
                detail="Upload rate limit exceeded. Try again later."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
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

    def get_queryset(self):
        user = self.request.user

        if user.tenant_id is None:
            return Document.objects.none()

        return Document.objects.filter(
            tenant_id=user.tenant_id
        ).select_related("department")

    def get_object(self):
        document = super().get_object()
        user = self.request.user

        if (
            user.role != "Admin"
            and document.department_id != user.department_id
        ):
            raise PermissionDenied(
                "You do not have permission to access this document."
            )

        return document


class DocumentDeleteView(generics.DestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsDepartmentMember]

    def get_queryset(self):
        user = self.request.user

        if user.tenant_id is None:
            return Document.objects.none()

        return Document.objects.filter(
            tenant_id=user.tenant_id
        )

    def get_object(self):
        document = super().get_object()
        user = self.request.user

        if (
            document.uploaded_by_id != user.id
            and user.role != "Admin"
        ):
            raise PermissionDenied(
                "You do not have permission to delete this document."
            )

        return document

    def perform_destroy(self, instance):
        if instance.file_path:
            instance.file_path.delete(save=False)

        instance.delete()
        create_audit_log(self.request.user, "DELETE")
