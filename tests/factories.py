
import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from tenants.models import Tenant
from departments.models import Department
from documents.models import Document, DocumentChunk
from api.models import ChatAnswer, AnswerFeedback


User = get_user_model()


def create_department(tenant, name, creator=None):
    """
    Create a department the same way the API does.

    Goes through the post_save signal (so the cold-start guide is
    created when an author exists) and, when `creator` is given, through
    the attribution scope the API uses.
    """

    from departments.signals import attributed_to

    with attributed_to(creator):
        return Department.objects.create(tenant=tenant, name=name)


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


class ChatAnswerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChatAnswer

    user = factory.SubFactory(UserFactory)
    tenant = factory.LazyAttribute(lambda answer: answer.user.tenant)
    conversation_id = factory.Sequence(lambda n: f"test-conversation-{n}")
    question = "What is the annual leave policy?"
    answer = "Employees receive 20 days of annual leave."
    citations = factory.LazyFunction(list)
    is_complete = True


class AnswerFeedbackFactory(factory.django.DjangoModelFactory):
    """
    A verdict on an answer.

    `user` defaults to the answer's author because the API only accepts
    feedback from the person who asked; anything else would build rows
    the real system can never produce.
    """

    class Meta:
        model = AnswerFeedback

    answer = factory.SubFactory(ChatAnswerFactory)
    user = factory.LazyAttribute(lambda feedback: feedback.answer.user)
    tenant = factory.LazyAttribute(
        lambda feedback: feedback.answer.user.tenant
    )
    is_positive = True
    user_comment = ""
