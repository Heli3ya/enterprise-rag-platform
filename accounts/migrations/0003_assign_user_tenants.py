from django.db import migrations
from django.db.models import OuterRef, Subquery


def assign_user_tenants(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Department = apps.get_model("departments", "Department")
    User = apps.get_model("accounts", "User")

    database = schema_editor.connection.alias

    default_tenant, _ = Tenant.objects.using(database).get_or_create(
        name="Default Organization",
        defaults={"is_active": True},
    )

    # Keep users without an assigned tenant in the default organization.
    User.objects.using(database).filter(
        tenant__isnull=True
    ).update(
        tenant_id=default_tenant.pk
    )

    # Assign each user to the tenant of their department when available.
    department_tenants = (
        Department.objects.using(database)
        .filter(tenant__isnull=False)
        .values("pk")
    )

    tenant_subquery = (
        Department.objects.using(database)
        .filter(pk=OuterRef("department_id"))
        .values("tenant_id")[:1]
    )

    User.objects.using(database).filter(
        tenant_id=default_tenant.pk,
        department_id__in=department_tenants,
    ).update(
        tenant_id=Subquery(tenant_subquery)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("departments", "0003_assign_default_tenant"),
        ("accounts", "0002_user_tenant_alter_user_role"),
    ]

    operations = [
        migrations.RunPython(
            assign_user_tenants,
            reverse_code=migrations.RunPython.noop,
        ),
    ]