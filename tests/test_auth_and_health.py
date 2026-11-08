from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from api.services import AIServiceUnavailable
from tests.factories import AdminFactory, UserFactory


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_login_returns_tokens_for_valid_credentials(client):
    user = UserFactory()

    response = client.post(
        "/api/auth/login/",
        {
            "username": user.username,
            "password": "TestPassword123!",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["access"]
    assert response.json()["refresh"]


@pytest.mark.django_db
def test_login_trims_surrounding_whitespace(client):
    user = UserFactory()

    response = client.post(
        "/api/auth/login/",
        {
            "username": f"  {user.username}  ",
            "password": "TestPassword123!",
        },
        format="json",
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_login_with_wrong_password_returns_specific_error(client):
    user = UserFactory()

    response = client.post(
        "/api/auth/login/",
        {
            "username": user.username,
            "password": "definitely-wrong",
        },
        format="json",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


@pytest.mark.django_db
def test_login_requires_both_fields(client):
    response = client.post(
        "/api/auth/login/",
        {"username": "someone"},
        format="json",
    )

    assert response.status_code == 400
    assert "required" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_login_rejects_deactivated_account(client):
    user = UserFactory(is_active=False)

    response = client.post(
        "/api/auth/login/",
        {
            "username": user.username,
            "password": "TestPassword123!",
        },
        format="json",
    )

    assert response.status_code == 401
    assert "deactivated" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_login_rejects_user_without_organization(client):
    user = UserFactory(tenant=None)

    response = client.post(
        "/api/auth/login/",
        {
            "username": user.username,
            "password": "TestPassword123!",
        },
        format="json",
    )

    assert response.status_code == 403
    assert "organization" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_health_endpoint_is_public_and_reports_dependencies(client):
    ai_response = MagicMock()
    ai_response.json.return_value = {
        "status": "ok",
        "ready": True,
    }

    with patch(
        "api.views.requests.get",
        return_value=ai_response,
    ):
        response = client.get("/api/health/")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["ai_service"]["status"] == "connected"


@pytest.mark.django_db
def test_health_endpoint_reports_degraded_ai_service(client):
    with patch(
        "api.views.requests.get",
        side_effect=RuntimeError("connection refused"),
    ):
        response = client.get("/api/health/")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "degraded"
    assert payload["ai_service"]["status"] == "unavailable"


@pytest.mark.django_db
def test_search_returns_503_when_ai_service_is_unavailable():
    user = AdminFactory()
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    with patch(
        "api.views.hybrid_search",
        side_effect=AIServiceUnavailable("AI service is unavailable"),
    ):
        response = api_client.post(
            "/api/search/",
            {"query": "annual leave"},
            format="json",
        )

    assert response.status_code == 503
    assert "not available" in response.json()["error"]


@pytest.mark.django_db
def test_search_passes_the_authenticated_user_to_the_search_layer():
    user = AdminFactory()
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    with patch(
        "api.views.hybrid_search",
        return_value=[],
    ) as search:
        response = api_client.post(
            "/api/search/",
            {"query": "annual leave"},
            format="json",
        )

    assert response.status_code == 200
    assert search.call_args.kwargs["user"] == user


@pytest.mark.django_db
def test_search_requires_a_department():
    user = AdminFactory(department=None)
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/search/",
        {"query": "annual leave"},
        format="json",
    )

    assert response.status_code == 403
    assert "department" in response.json()["detail"].lower()
