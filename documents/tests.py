
import tempfile

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document
from documents.serializers import DocumentSerializer


def create_test_department(
    name="IT",
    tenant_name="Document Test Organization",
):
    tenant = Tenant.objects.create(name=tenant_name)

    return Department.objects.create(
        name=name,
        tenant=tenant,
    )


class DocumentModelTest(TestCase):
    def test_create_document(self):
        User = get_user_model()
        department = create_test_department()

        user = User.objects.create_user(
            username="tester",
            password="123456",
            role="Member",
            department=department,
            tenant=department.tenant,
        )

        document = Document.objects.create(
            title="Test Document",
            file_type="text/plain",
            uploaded_by=user,
            department=department,
            tenant=department.tenant,
        )

        self.assertEqual(document.title, "Test Document")
        self.assertEqual(str(document), "Test Document")

    def test_documents_are_stored_in_separate_tenant_folders(self):
        User = get_user_model()

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                department_a = create_test_department(
                    name="IT",
                    tenant_name="Storage Tenant A",
                )

                department_b = create_test_department(
                    name="IT",
                    tenant_name="Storage Tenant B",
                )

                user_a = User.objects.create_user(
                    username="storage_user_a",
                    password="123456",
                    role="Member",
                    department=department_a,
                    tenant=department_a.tenant,
                )

                user_b = User.objects.create_user(
                    username="storage_user_b",
                    password="123456",
                    role="Member",
                    department=department_b,
                    tenant=department_b.tenant,
                )

                document_a = Document.objects.create(
                    title="Tenant A Document",
                    file_type="text/plain",
                    uploaded_by=user_a,
                    department=department_a,
                    tenant=department_a.tenant,
                    file_path=SimpleUploadedFile(
                        "shared-name.txt",
                        b"Tenant A private content",
                        content_type="text/plain",
                    ),
                )

                document_b = Document.objects.create(
                    title="Tenant B Document",
                    file_type="text/plain",
                    uploaded_by=user_b,
                    department=department_b,
                    tenant=department_b.tenant,
                    file_path=SimpleUploadedFile(
                        "shared-name.txt",
                        b"Tenant B private content",
                        content_type="text/plain",
                    ),
                )

                self.assertTrue(
                    document_a.file_path.name.startswith(
                        f"documents/tenant_{department_a.tenant_id}/"
                    ),
                    document_a.file_path.name,
                )

                self.assertTrue(
                    document_b.file_path.name.startswith(
                        f"documents/tenant_{department_b.tenant_id}/"
                    ),
                    document_b.file_path.name,
                )

                self.assertNotEqual(
                    document_a.file_path.name,
                    document_b.file_path.name,
                )

                self.assertTrue(
                    document_a.file_path.storage.exists(
                        document_a.file_path.name
                    )
                )

                self.assertTrue(
                    document_b.file_path.storage.exists(
                        document_b.file_path.name
                    )
                )


class DocumentSerializerTest(TestCase):
    def test_valid_document_serializer(self):
        department = create_test_department()

        file = SimpleUploadedFile(
            "test.txt",
            b"test document content",
            content_type="text/plain",
        )

        data = {
            "title": "Valid Document",
            "file_path": file,
            "department": department.id,
        }

        serializer = DocumentSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_empty_title_validation(self):
        department = create_test_department()

        file = SimpleUploadedFile(
            "test.txt",
            b"test document content",
            content_type="text/plain",
        )

        data = {
            "title": "",
            "file_path": file,
            "department": department.id,
        }

        serializer = DocumentSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)

    def test_allowed_pdf_file_upload(self):
        department = create_test_department()

        file = SimpleUploadedFile(
            "test.pdf",
            b"%PDF-1.4 test pdf content",
            content_type="application/pdf",
        )

        data = {
            "title": "PDF Document",
            "file_path": file,
            "department": department.id,
        }

        serializer = DocumentSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_file_type_upload(self):
        department = create_test_department()

        file = SimpleUploadedFile(
            "test.exe",
            b"MZ" + b"\x00" * 100,
            content_type="application/octet-stream",
        )

        data = {
            "title": "Invalid File",
            "file_path": file,
            "department": department.id,
        }

        serializer = DocumentSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("file_path", serializer.errors)


class DocumentEndpointTest(TestCase):
    def setUp(self):
        User = get_user_model()

        self.department = create_test_department(
            tenant_name="Document Endpoint Test Organization"
        )

        self.user = User.objects.create_user(
            username="apiuser",
            password="123456",
            role="Member",
            department=self.department,
            tenant=self.department.tenant,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.document = Document.objects.create(
            title="Delete Test",
            uploaded_by=self.user,
            department=self.department,
            tenant=self.department.tenant,
            file_type="text/plain",
        )

    def test_delete_document_success(self):
        response = self.client.delete(
            f"/api/documents/{self.document.id}/delete/"
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_document_forbidden(self):
        User = get_user_model()

        another_user = User.objects.create_user(
            username="another",
            password="123456",
            role="Member",
            department=self.department,
            tenant=self.department.tenant,
        )

        self.client.force_authenticate(user=another_user)

        response = self.client.delete(
            f"/api/documents/{self.document.id}/delete/"
        )

        self.assertEqual(response.status_code, 403)

    def test_get_document_success(self):
        response = self.client.get(
            f"/api/documents/{self.document.id}/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Delete Test")

    def test_upload_document_bad_request(self):
        data = {
            "title": "",
            "department": self.department.id,
        }

        response = self.client.post("/api/documents/", data)

        self.assertEqual(response.status_code, 400)

    def test_upload_document_saves_file_size(self):
        content = b"Analytics file size test"

        uploaded_file = SimpleUploadedFile(
            "analytics_size_test.txt",
            content,
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/documents/",
            {
                "title": "Analytics Size Test",
                "department": self.department.id,
                "file_path": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 201, response.data)

        document = Document.objects.get(
            id=response.data["document_id"],
        )

        self.assertEqual(document.file_size, len(content))
