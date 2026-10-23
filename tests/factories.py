
import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document, DocumentChunk


User = get_user_model()


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Test Organization {n}")
    is_active = True


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Test Department {n}")
    description = "Department created for automated tests"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"test_user_{n}")
    password = factory.LazyFunction(
        lambda: make_password("TestPassword123!")
    )
    role = "Member"
    department = factory.SubFactory(DepartmentFactory)
    tenant = factory.LazyAttribute(
        lambda user: (
            user.department.tenant
            if user.department is not None
            else TenantFactory()
        )
    )


class AdminFactory(UserFactory):
    username = factory.Sequence(lambda n: f"test_admin_{n}")
    role = "Admin"


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    title = factory.Sequence(lambda n: f"Test Document {n}")
    file_type = "text/plain"
    status = "Pending"
    file_size = 0
    uploaded_by = factory.SubFactory(UserFactory)
    department = factory.LazyAttribute(
        lambda document: document.uploaded_by.department
    )
    tenant = factory.LazyAttribute(
        lambda document: document.uploaded_by.tenant
    )


class DocumentChunkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DocumentChunk

    document = factory.SubFactory(DocumentFactory)
    content = "Sample content for automated integration tests."
    chunk_index = 0
