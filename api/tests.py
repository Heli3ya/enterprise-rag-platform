
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document, SearchQuery


class AdminAnalyticsAPITest(APITestCase):
    def setUp(self):
        User = get_user_model()

        self.tenant = Tenant.objects.create(
            name="Analytics Test Organization"
        )

        self.department = Department.objects.create(
            name="IT",
            tenant=self.tenant,
        )
        self.other_department = Department.objects.create(
            name="HR",
            tenant=self.tenant,
        )

        self.admin = User.objects.create_user(
            username="analytics_admin",
            password="TestPassword123!",
            role="Admin",
            department=self.department,
            tenant=self.tenant,
        )
        self.member = User.objects.create_user(
            username="analytics_member",
            password="TestPassword123!",
            role="Member",
            department=self.department,
            tenant=self.tenant,
        )

        Document.objects.create(
            title="IT Document",
            file_path="documents/it.txt",
            file_type="txt",
            status="Indexed",
            uploaded_by=self.admin,
            department=self.department,
            tenant=self.tenant,
            file_size=1200,
        )
        Document.objects.create(
            title="HR Document",
            file_path="documents/hr.pdf",
            file_type="pdf",
            status="Pending",
            uploaded_by=self.admin,
            department=self.other_department,
            tenant=self.tenant,
            file_size=3500,
        )

        SearchQuery.objects.create(
            user=self.member,
            tenant=self.tenant,
            query_text="test IT search",
        )
        SearchQuery.objects.create(
            user=self.admin,
            tenant=self.tenant,
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
    def test_admin_analytics_excludes_other_tenant_data(self):
        other_tenant = Tenant.objects.create(
            name="Other Analytics Organization"
        )
        other_department = Department.objects.create(
            name="Other Tenant Finance",
            tenant=other_tenant,
        )
        other_admin = get_user_model().objects.create_user(
            username="other_tenant_analytics_admin",
            password="TestPassword123!",
            role="Admin",
            department=other_department,
            tenant=other_tenant,
        )

        Document.objects.create(
            title="Other Tenant Secret Document",
            file_path="documents/other-tenant.txt",
            file_type="txt",
            status="Indexed",
            uploaded_by=other_admin,
            department=other_department,
            tenant=other_tenant,
            file_size=9999,
        )
        SearchQuery.objects.create(
            user=other_admin,
            tenant=other_tenant,
            query_text="OTHER TENANT SECRET SEARCH",
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)

        assert response.status_code == 200
        assert response.data["total_documents"] == 2
        assert response.data["total_searches"] == 2
        assert "Other Tenant Finance" not in str(response.data)
        assert "Other Tenant Secret Document" not in str(response.data)
        assert "OTHER TENANT SECRET SEARCH" not in str(response.data)
