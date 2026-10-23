
from django.db import migrations
from django.db.models import OuterRef, Subquery


def assign_document_tenants(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Department = apps.get_model("departments", "Department")
    User = apps.get_model("accounts", "User")
    Document = apps.get_model("documents", "Document")
    SearchQuery = apps.get_model("documents", "SearchQuery")

    database = schema_editor.connection.alias

    default_tenant, _ = Tenant.objects.using(database).get_or_create(
        name="Default Organization",
        defaults={"is_active": True},
    )

    # Assign documents to the tenant of their department.
    document_tenant = (
        Department.objects.using(database)
        .filter(pk=OuterRef("department_id"))
        .values("tenant_id")[:1]
    )

    Document.objects.using(database).filter(
        tenant__isnull=True,
        department__tenant__isnull=False,
    ).update(
        tenant=Subquery(document_tenant)
    )

    # Fallback for legacy documents whose department has no tenant.
    Document.objects.using(database).filter(
        tenant__isnull=True,
    ).update(
        tenant_id=default_tenant.pk
    )

    # Assign search history to the tenant of the user who created it.
    search_tenant = (
        User.objects.using(database)
        .filter(pk=OuterRef("user_id"))
        .values("tenant_id")[:1]
    )

    SearchQuery.objects.using(database).filter(
        tenant__isnull=True,
        user__tenant__isnull=False,
    ).update(
        tenant=Subquery(search_tenant)
    )

    # Fallback for legacy history whose user has no tenant.
    SearchQuery.objects.using(database).filter(
        tenant__isnull=True,
    ).update(
        tenant_id=default_tenant.pk
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("departments", "0003_assign_default_tenant"),
        ("accounts", "0003_assign_user_tenants"),
        ("documents", "0011_document_tenant_searchquery_tenant"),
    ]

    operations = [
        migrations.RunPython(
            assign_document_tenants,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
