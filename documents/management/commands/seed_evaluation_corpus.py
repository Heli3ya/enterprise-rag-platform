"""
Seed the sample organisational corpus used by the RAG evaluation.

The evaluation dataset (``ai_service/evaluation/dataset.jsonl``) refers
to six policy documents. Without those documents in the database the
retriever has nothing to find and every score is meaningless, so this
command ingests them synchronously: create the row, store the file,
chunk the text, embed every chunk and mark the document Indexed.

It is idempotent. Re-running skips documents that already exist unless
``--reset`` is passed, in which case the old rows and files are removed
first.

Example
-------
    python manage.py seed_evaluation_corpus \\
        --tenant "Acme Corporation" --department "People Operations"
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.services import generate_embeddings
from departments.models import Department
from documents.chunking import chunk_text
from documents.models import Document, DocumentChunk, Embedding
from tenants.models import Tenant


EMBEDDING_BATCH_SIZE = 16
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"


def default_corpus_dir():
    return Path(settings.BASE_DIR) / "ai_service" / "evaluation" / "corpus"


class Command(BaseCommand):
    help = "Ingest the sample evaluation corpus into a tenant/department."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            required=True,
            help="Tenant name (created if it does not exist).",
        )
        parser.add_argument(
            "--department",
            required=True,
            help="Department name inside the tenant (created if missing).",
        )
        parser.add_argument(
            "--corpus-dir",
            default=None,
            help="Directory with the .txt corpus (default: ai_service/evaluation/corpus).",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Username recorded as the uploader (default: first Admin).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and re-ingest documents that already exist.",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=400,
            help="Tokens per chunk (300-500, default 400).",
        )
        parser.add_argument(
            "--overlap",
            type=int,
            default=10,
            help="Chunk overlap percentage (10-15, default 10).",
        )

    # -- helpers --------------------------------------------------------

    def _resolve_tenant(self, name):
        tenant, created = Tenant.objects.get_or_create(
            name=name,
            defaults={"is_active": True},
        )

        if created:
            self.stdout.write(f"Created tenant '{tenant.name}' (id={tenant.id}).")

        return tenant

    def _resolve_department(self, tenant, name):
        department, created = Department.objects.get_or_create(
            tenant=tenant,
            name=name,
        )

        if created:
            self.stdout.write(
                f"Created department '{department.name}' (id={department.id})."
            )

        return department

    def _resolve_user(self, tenant, username):
        user_model = get_user_model()

        if username:
            user = user_model.objects.filter(username=username).first()

            if user is None:
                raise CommandError(f"Unknown user '{username}'.")

            return user

        user = (
            user_model.objects
            .filter(tenant=tenant, role="Admin")
            .order_by("id")
            .first()
        )

        if user is None:
            user = (
                user_model.objects
                .filter(tenant=tenant)
                .order_by("id")
                .first()
            )

        if user is None:
            raise CommandError(
                "No user exists for this tenant. Create one first or pass "
                "--user."
            )

        return user

    def _delete_document(self, document):
        if document.file_path:
            try:
                document.file_path.delete(save=False)
            except Exception:
                pass

        document.delete()

    # -- command --------------------------------------------------------

    def handle(self, *args, **options):
        corpus_dir = Path(options["corpus_dir"] or default_corpus_dir())

        if not corpus_dir.is_dir():
            raise CommandError(f"Corpus directory not found: {corpus_dir}")

        corpus_files = sorted(corpus_dir.glob("*.txt"))

        if not corpus_files:
            raise CommandError(f"No .txt files in {corpus_dir}")

        tenant = self._resolve_tenant(options["tenant"])
        department = self._resolve_department(tenant, options["department"])
        user = self._resolve_user(tenant, options["user"])

        summary = {
            "tenant_id": tenant.id,
            "tenant": tenant.name,
            "department_id": department.id,
            "department": department.name,
            "uploaded_by": user.username,
            "created": [],
            "replaced": [],
            "skipped": [],
            "failed": [],
            "chunks": 0,
        }

        for path in corpus_files:
            title = path.name
            existing = Document.objects.filter(
                tenant=tenant,
                title=title,
            ).first()

            if existing is not None and not options["reset"]:
                summary["skipped"].append(title)
                self.stdout.write(f"skip     {title} (already indexed)")
                continue

            if existing is not None:
                self._delete_document(existing)
                summary["replaced"].append(title)

            try:
                chunks_created = self._ingest(
                    path,
                    tenant=tenant,
                    department=department,
                    user=user,
                    chunk_size=options["chunk_size"],
                    overlap=options["overlap"],
                )
            except Exception as exc:
                summary["failed"].append({"document": title, "error": str(exc)})
                self.stderr.write(f"FAILED   {title}: {exc}")
                continue

            if title not in summary["replaced"]:
                summary["created"].append(title)

            summary["chunks"] += chunks_created

            self.stdout.write(
                f"indexed  {title} ({chunks_created} chunks)"
            )

        self.stdout.write("")
        self.stdout.write(json.dumps(summary, indent=2))

        if summary["failed"]:
            raise CommandError(
                f"{len(summary['failed'])} document(s) failed to ingest."
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Evaluation scope: "
                f"tenant_id={tenant.id} department_ids={department.id}"
            )
        )
        self.stdout.write(
            "Run the evaluation with: "
            f"python -m evaluation --tenant-id {tenant.id} "
            f"--department-ids {department.id}"
        )

    def _ingest(self, path, *, tenant, department, user, chunk_size, overlap):
        text = path.read_text(encoding="utf-8")

        if not text.strip():
            raise CommandError(f"{path.name} is empty.")

        chunks = chunk_text(
            text,
            chunk_size=chunk_size,
            overlap_percent=overlap,
        )

        if not chunks:
            raise CommandError(f"{path.name} produced no chunks.")

        document = Document(
            tenant=tenant,
            title=path.name,
            file_type="text/plain",
            status="Processing",
            uploaded_by=user,
            department=department,
            file_size=len(text.encode("utf-8")),
        )

        document.file_path.save(
            path.name,
            ContentFile(text.encode("utf-8")),
            save=False,
        )
        document.save()

        with transaction.atomic():
            chunk_objects = [
                DocumentChunk(
                    document=document,
                    content=chunk,
                    chunk_index=index,
                )
                for index, chunk in enumerate(chunks)
            ]
            DocumentChunk.objects.bulk_create(chunk_objects)

            for start in range(0, len(chunk_objects), EMBEDDING_BATCH_SIZE):
                batch = chunk_objects[start:start + EMBEDDING_BATCH_SIZE]
                vectors, _ = generate_embeddings([item.content for item in batch])

                if len(vectors) != len(batch):
                    raise CommandError(
                        "Embedding count does not match chunk count."
                    )

                Embedding.objects.bulk_create(
                    [
                        Embedding(
                            chunk=item,
                            embedding_vector=vector,
                            model_name=EMBEDDING_MODEL_NAME,
                        )
                        for item, vector in zip(batch, vectors)
                    ]
                )

            document.status = "Indexed"
            document.save(update_fields=["status"])

        return len(chunk_objects)
