
from .models import AuditLog


def create_audit_log(user, action):
    tenant_id = getattr(user, "tenant_id", None)

    AuditLog.objects.create(
        user=user,
        tenant_id=tenant_id,
        action=action,
    )
