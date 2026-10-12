from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from departments.models import Department
from documents.models import Document, SearchQuery


class AdminAnalyticsAPITest(APITestCase):
    def setUp(self):
        User = get_user_model()

        self.department = Department.objects.create(name="IT")
        self.other_department = Department.objects.create(name="HR")

        self.admin = User.objects.create_user(
            username="analytics_admin",
            password="TestPassword123!",
            role="Admin",
            department=self.department,
        )
        self.member = User.objects.create_user(
            username="analytics_member",
            password="TestPassword123!",
            role="Member",
            department=self.department,
        )

        Document.objects.create(
            title="IT Document",
            file_path="documents/it.txt",
            file_type="txt",
            status="Indexed",
            uploaded_by=self.admin,
            department=self.department,
            file_size=1200,
        )
        Document.objects.create(
            title="HR Document",
            file_path="documents/hr.pdf",
            file_type="pdf",
            status="Pending",
            uploaded_by=self.admin,
            department=self.other_department,
            file_size=3500,
        )

        SearchQuery.objects.create(
            user=self.member,
            query_text="test IT search",
        )
        SearchQuery.objects.create(
            user=self.admin,
            query_text="test admin search",
        )

        self.url = reverse("admin_analytics")

    def test_admin_receives_correct_analytics(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_documents"], 2)
        self.assertEqual(response.data["total_file_size_bytes"], 4700)
        self.assertEqual(response.data["total_searches"], 2)
        self.assertEqual(len(response.data["departments"]), 2)
        self.assertEqual(len(response.data["recent_searches"]), 2)

        departments = {
            item["department_name"]: item
            for item in response.data["departments"]
        }

        self.assertEqual(departments["IT"]["document_count"], 1)
        self.assertEqual(departments["IT"]["file_size_bytes"], 1200)
        self.assertEqual(departments["IT"]["search_count"], 2)

        self.assertEqual(departments["HR"]["document_count"], 1)
        self.assertEqual(departments["HR"]["file_size_bytes"], 3500)
        self.assertEqual(departments["HR"]["search_count"], 0)

    def test_member_cannot_access_analytics(self):
        self.client.force_authenticate(user=self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_cannot_access_analytics(self):
        response = self.client.get(self.url)

        self.assertIn(response.status_code, (401, 403))
