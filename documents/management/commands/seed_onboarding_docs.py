"""
Backfill the cold-start guide for departments created before it existed.

The post_save signal covers every department created from now on, but a
deployment also has older departments whose knowledge base is still
empty. Run this once after deploying, or any time a guide went missing:

    python manage.py seed_onboarding_docs
    python manage.py seed_onboarding_docs --tenant-id 3 --dry-run

The command is idempotent: departments that already have a guide are
skipped, so it is safe to run on every release.
"""

from django.core.management.base import BaseCommand

from departments.models import Department
from documents.models import Document
from documents.onboarding import (
    ensure_onboarding_document,
    resolve_guide_author,
)


class Command(BaseCommand):
    help = (
        "Create the onboarding guide for departments that do not have "
        "one yet."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=None,
            help="Only seed departments of this organization.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        dry_run = options["dry_run"]

        departments = (
            Department.objects
            .select_related("tenant")
            .order_by("id")
        )

        if tenant_id is not None:
            departments = departments.filter(tenant_id=tenant_id)

        existing_ids = set(
            Document.objects
            .filter(is_system=True)
            .values_list("department_id", flat=True)
        )

        created = 0
        skipped = 0
        failed = 0

        for department in departments.iterator():
            if department.id in existing_ids:
                skipped += 1
                continue

            author = resolve_guide_author(department)

            if author is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped department {department.id} "
                        f"({department.name}): no active user to "
                        "attribute the guide to."
                    )
                )
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"Would create a guide for department "
                    f"{department.id} ({department.name})."
                )
                created += 1
                continue

            try:
                document = ensure_onboarding_document(
                    department,
                    created_by=author,
                )
            except Exception as exc:  # pragma: no cover - defensive
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed for department {department.id} "
                        f"({department.name}): {exc}"
                    )
                )
                continue

            if document is None:
                skipped += 1
            else:
                created += 1
                self.stdout.write(
                    f"Created guide {document.id} for department "
                    f"{department.id} ({department.name})."
                )

        prefix = "[dry-run] " if dry_run else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}created={created} skipped={skipped} "
                f"failed={failed}"
            )
        )
