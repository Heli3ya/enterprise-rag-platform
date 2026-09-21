from .models import AuditLog


def create_audit_log(user, action):
    AuditLog.objects.create(
        user=user,
        action=action,
    )