from django.test import TestCase
from django.contrib.auth import get_user_model
from departments.models import Department
from documents.models import Document
from documents.serializers import DocumentSerializer
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from django.urls import reverse


class DocumentModelTest(TestCase):

    def test_create_document(self):

        User = get_user_model()

        department = Department.objects.create(
            name="IT"
        )

        user = User.objects.create_user(
            username="tester",
            password="123456",
            role="Member",
            department=department
        )

        document = Document.objects.create(
            title="Test Document",
            file_type="text/plain",
            uploaded_by=user,
            department=department
        )

        self.assertEqual(
            document.title,
            "Test Document"
        )

        self.assertEqual(
            str(document),
            "Test Document"
        )

class DocumentSerializerTest(TestCase):

    def test_valid_document_serializer(self):

        department = Department.objects.create(
            name="IT"
        )

        file = SimpleUploadedFile(
            "test.txt",
            b"test document content",
            content_type="text/plain"
        )

        data = {
            "title": "Valid Document",
            "file_path": file,
            "department": department.id
        }

        serializer = DocumentSerializer(
            data=data
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors
        )

    def test_empty_title_validation(self):

        department = Department.objects.create(
            name="IT"
        )

        file = SimpleUploadedFile(
            "test.txt",
            b"test document content",
            content_type="text/plain"
        )

        data = {
            "title": "",
            "file_path": file,
            "department": department.id
        }

        serializer = DocumentSerializer(
            data=data
        )

        self.assertFalse(
            serializer.is_valid()
        )

        self.assertIn(
            "title",
            serializer.errors
        )
    def test_allowed_pdf_file_upload(self):

        department = Department.objects.create(
            name="IT"
        )

        file = SimpleUploadedFile(
            "test.pdf",
            b"%PDF-1.4 test pdf content",
            content_type="application/pdf"
        )

        data = {
            "title": "PDF Document",
            "file_path": file,
            "department": department.id
        }

        serializer = DocumentSerializer(
            data=data
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors
        )

    def test_invalid_file_type_upload(self):

        department = Department.objects.create(
            name="IT"
        )

        file = SimpleUploadedFile(
           "test.exe",
           b"MZ" + b"\x00" * 100,
           content_type="application/octet-stream"
)

        data = {
            "title": "Invalid File",
            "file_path": file,
            "department": department.id
        }

        serializer = DocumentSerializer(
            data=data
        )

        self.assertFalse(
            serializer.is_valid()
        )

        self.assertIn(
            "file_path",
            serializer.errors
        )
class DocumentEndpointTest(TestCase):

    def setUp(self):

        User = get_user_model()

        self.department = Department.objects.create(
            name="IT"
        )

        self.user = User.objects.create_user(
            username="apiuser",
            password="123456",
            role="Member",
            department=self.department
        )

        self.client = APIClient()

        self.client.force_authenticate(
            user=self.user
        )

        self.document = Document.objects.create(
            title="Delete Test",
            uploaded_by=self.user,
            department=self.department,
            file_type="text/plain"
        )


    def test_delete_document_success(self):

        response = self.client.delete(
            f"/api/documents/{self.document.id}/delete/"
        )

        self.assertEqual(
            response.status_code,
            204
        )

    def test_delete_document_forbidden(self):

        User = get_user_model()

        another_user = User.objects.create_user(
            username="another",
            password="123456",
            role="Member",
            department=self.department
        )

        self.client.force_authenticate(
            user=another_user
        )

        response = self.client.delete(
            f"/api/documents/{self.document.id}/delete/"
        )

        self.assertEqual(
            response.status_code,
            403
        )
    def test_get_document_success(self):

        response = self.client.get(
            f"/api/documents/{self.document.id}/"
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.data["title"],
            "Delete Test"
        )
    def test_upload_document_bad_request(self):

        data = {
            "title": "",
            "department": self.department.id
        }

        response = self.client.post(
            "/api/documents/",
            data
        )

        self.assertEqual(
            response.status_code,
            400
        )
    def test_upload_document_saves_file_size(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

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
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        document = Document.objects.get(
            id=response.data["document_id"],
        )

        self.assertEqual(
            document.file_size,
            len(content),
        )
