
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from api.permissions import IsAdminUser
from .models import Department
from .serializers import DepartmentSerializer


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

        serializer.save(tenant_id=user.tenant_id)
