
import logging
import mimetypes
from urllib.parse import quote

import magic

from django.db import transaction
from django.http import FileResponse, Http404
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import OpenApiParameter, extend_schema

from api.audit import create_audit_log
from api.permissions import IsDepartmentMember

from .highlighting import find_highlights
from .links import document_file_url
from .models import Document, DocumentChunk
from .preview import (
    PreviewFileMissing,
    PreviewUnavailable,
    extract_document_text,
)
from .serializers import (
    DocumentSerializer,
    DocumentStatusSerializer,
    DocumentListSerializer,
    ChunkDetailSerializer,
)
from .tasks import process_document


logger = logging.getLogger(__name__)


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

        def enqueue_processing():
            try:
                process_document.delay(document.id)
            except Exception:
                # A broker outage must not turn a successful upload into
                # a 500 response, and the document must not stay
                # "Pending" forever.
                logger.exception(
                    "Failed to enqueue processing for document %s",
                    document.id,
                )
                Document.objects.filter(id=document.id).update(
                    status="Failed",
                )

        transaction.on_commit(enqueue_processing)

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


def can_access_document(user, document):
    """
    Single source of truth for "may this user read this document?".

    Mirrors the rules already enforced by search and citations:
    same tenant, and same department unless the user is an Admin.
    """

    if not user or not user.is_authenticated:
        return False

    if user.tenant_id is None or document.tenant_id != user.tenant_id:
        return False

    if document.department.tenant_id != user.tenant_id:
        return False

    if user.role == "Admin":
        return True

    return document.department_id == user.department_id


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="q",
            type=str,
            location=OpenApiParameter.QUERY,
            description=(
                "The question that produced this citation. When provided, "
                "`highlights` marks the matching ranges inside `content`."
            ),
        ),
    ],
)
class ChunkDetailView(generics.RetrieveAPIView):
    """
    Resolve a citation marker (`[93]`) into the passage that was
    actually retrieved, plus the document it came from.
    """

    serializer_class = ChunkDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.tenant_id is None:
            return DocumentChunk.objects.none()

        return (
            DocumentChunk.objects
            .select_related(
                "document",
                "document__department",
                "document__uploaded_by",
            )
            .filter(
                document__tenant_id=user.tenant_id,
                document__department__tenant_id=user.tenant_id,
            )
        )

    def get_object(self):
        chunk = super().get_object()

        if not can_access_document(self.request.user, chunk.document):
            raise PermissionDenied(
                "You do not have permission to access this citation."
            )

        return chunk


class DocumentFileView(generics.GenericAPIView):
    """
    Serve the original uploaded file behind authentication.

    The `/media/` URL is intentionally not used here: it is public
    and would let anyone who guesses a path read tenant documents.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DocumentStatusSerializer

    def get(self, request, pk):
        document = (
            Document.objects
            .select_related("department")
            .filter(pk=pk)
            .first()
        )

        if document is None:
            raise Http404("Document not found.")

        if not can_access_document(request.user, document):
            raise PermissionDenied(
                "You do not have permission to access this file."
            )

        try:
            file_handle = document.file_path.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404("The stored file is no longer available.")

        filename = document.file_path.name.rsplit("/", 1)[-1] or "document"

        content_type = (
            document.file_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )

        response = FileResponse(
            file_handle,
            content_type=content_type,
            as_attachment=False,
        )

        # Browsers must not re-interpret the bytes as HTML/JS even if
        # a file was uploaded with a misleading name.
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox"

        # RFC 5987 encoding keeps non-ASCII filenames intact.
        response["Content-Disposition"] = (
            f"inline; filename*=UTF-8''{quote(filename)}"
        )

        return response


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="q",
            type=str,
            location=OpenApiParameter.QUERY,
            description=(
                "The question behind the citation. When provided, "
                "`highlights` marks every matching range in `content`."
            ),
        ),
    ],
)
class DocumentPreviewView(generics.GenericAPIView):
    """
    Extracted text of a whole document, with the cited query highlighted.

    This is what makes "open the source" useful for formats the browser
    cannot render on its own (PDF, DOCX): the drawer shows the real
    document text and scrolls to the matched lines.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DocumentStatusSerializer

    def get(self, request, pk):
        document = (
            Document.objects
            .select_related("department")
            .filter(pk=pk)
            .first()
        )

        if document is None:
            raise Http404("Document not found.")

        if not can_access_document(request.user, document):
            raise PermissionDenied(
                "You do not have permission to access this document."
            )

        try:
            content, truncated = extract_document_text(document)
        except PreviewFileMissing as exc:
            raise Http404(str(exc))
        except PreviewUnavailable as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        highlights, matched_terms = find_highlights(
            content,
            request.query_params.get("q", ""),
        )

        return Response(
            {
                "document_id": document.id,
                "title": document.title,
                "filename": document.file_path.name.rsplit("/", 1)[-1],
                "file_type": document.file_type,
                "file_url": document_file_url(document.id),
                "department": document.department.name,
                "content": content,
                "highlights": highlights,
                "matched_terms": matched_terms,
                "truncated": truncated,
            },
            status=status.HTTP_200_OK,
        )

