from rest_framework.permissions import BasePermission
class IsAdminUser(BasePermission):
    """
    Allows access only to authenticated users
    whose role is Admin.
    """

    message = "Admin access is required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "Admin"
        )


class IsDepartmentMember(BasePermission):
    """
    Allows access only to authenticated users
    who belong to a department.
    """

    message = "Department membership is required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.department_id is not None
        )