
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema

from api.permissions import IsAdminUser
from documents.models import Document, DocumentChunk

from .models import Department
from .serializers import (
    DepartmentReadinessSerializer,
    DepartmentSerializer,
)
from .signals import attributed_to


class DepartmentListView(generics.ListAPIView):
    serializer_class = DepartmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant_id = self.request.user.tenant_id

        if tenant_id is None:
            return Department.objects.none()

        return Department.objects.filter(
            tenant_id=tenant_id
        ).order_by("name")


class DepartmentCreateView(generics.CreateAPIView):
    serializer_class = DepartmentSerializer
    permission_classes = [IsAdminUser]

    def perform_create(self, serializer):
        user = self.request.user

        if user.tenant_id is None:
            raise PermissionDenied(
                "Your account is not assigned to an organization."
            )

        # The post_save signal seeds the onboarding guide; this scope
        # tells it that the new document belongs to the admin who is
        # making the request.
        with attributed_to(user):
            serializer.save(tenant_id=user.tenant_id)


@extend_schema(
    summary="Is this department ready to answer questions?",
    description=(
        "Cheap, read-only probe used by the dashboard to choose between "
        "the cold-start empty state and the normal chat view.\n\n"
        "`document_count` ignores the auto-generated onboarding guide, "
        "so a brand-new department reports `is_empty: true` even though "
        "it already contains one searchable document."
    ),
    responses={200: DepartmentReadinessSerializer},
)
class DepartmentReadinessView(APIView):
    """
    Three bounded queries, no AI calls, no caching needed.

    The dashboard calls this once per page load, so it has to stay
    cheap: a count on an indexed foreign key, an `EXISTS` on chunks, and
    a single-row lookup for the guide.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.tenant_id is None:
            return Response(
                {"detail": "Your account is not assigned to an organization."},
                status=status.HTTP_403_FORBIDDEN,
            )

        department_id = getattr(user, "department_id", None)

        if department_id is None:
            return Response(
                {"detail": "Your account is not assigned to a department."},
                status=status.HTTP_403_FORBIDDEN,
            )

        documents = Document.objects.filter(
            tenant_id=user.tenant_id,
            department_id=department_id,
            department__tenant_id=user.tenant_id,
        )

        document_count = documents.filter(is_system=False).count()

        onboarding_document_id = (
            documents
            .filter(is_system=True)
            .order_by("id")
            .values_list("id", flat=True)
            .first()
        )

        has_searchable_content = DocumentChunk.objects.filter(
            document__tenant_id=user.tenant_id,
            document__department_id=department_id,
            document__department__tenant_id=user.tenant_id,
        ).exists()

        payload = {
            "department_id": department_id,
            "department_name": getattr(user.department, "name", ""),
            "document_count": document_count,
            "has_searchable_content": has_searchable_content,
            "is_empty": document_count == 0,
            "onboarding_document_id": onboarding_document_id,
        }

        return Response(
            DepartmentReadinessSerializer(payload).data,
            status=status.HTTP_200_OK,
        )
