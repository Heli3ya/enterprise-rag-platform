
import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from departments.models import Department
from documents.models import Document, DocumentChunk


User = get_user_model()


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

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


class DocumentChunkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DocumentChunk

    document = factory.SubFactory(DocumentFactory)
    content = "Sample content for automated integration tests."
    chunk_index = 0