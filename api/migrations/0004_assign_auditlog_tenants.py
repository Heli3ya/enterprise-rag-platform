
from django.db import migrations
from django.db.models import OuterRef, Subquery


def assign_auditlog_tenants(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    User = apps.get_model("accounts", "User")
    AuditLog = apps.get_model("api", "AuditLog")

    database = schema_editor.connection.alias

    default_tenant, _ = Tenant.objects.using(database).get_or_create(
        name="Default Organization",
        defaults={"is_active": True},
    )

    user_tenant = (
        User.objects.using(database)
        .filter(pk=OuterRef("user_id"))
        .values("tenant_id")[:1]
    )

    # Assign audit logs to the tenant of their associated user.
    AuditLog.objects.using(database).filter(
        tenant__isnull=True,
        user__tenant__isnull=False,
    ).update(
        tenant_id=Subquery(user_tenant)
    )

    # Keep logs without a user or without a tenant in the default organization.
    AuditLog.objects.using(database).filter(
        tenant__isnull=True,
    ).update(
        tenant_id=default_tenant.pk
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("accounts", "0003_assign_user_tenants"),
        ("api", "0003_auditlog_tenant"),
    ]

    operations = [
        migrations.RunPython(
            assign_auditlog_tenants,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
