
from django.db import migrations


def assign_default_tenant(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Department = apps.get_model("departments", "Department")

    tenant, _ = Tenant.objects.using(
        schema_editor.connection.alias
    ).get_or_create(
        name="Default Organization",
        defaults={"is_active": True},
    )

    Department.objects.using(
        schema_editor.connection.alias
    ).filter(
        tenant__isnull=True
    ).update(
        tenant_id=tenant.pk
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("departments", "0002_department_tenant"),
    ]

    operations = [
        migrations.RunPython(
            assign_default_tenant,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
