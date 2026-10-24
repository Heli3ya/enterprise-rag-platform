
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from llm_client import LLMClient


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "http://localhost:11434/api",
    )
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:3b")
    monkeypatch.delenv("LLM_API_KEY", raising=False)


def make_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def make_http_error_response(status_code):
    response = requests.Response()
    response.status_code = status_code
    response.url = "http://localhost:11434/api/generate"
    response._content = b'{"error": "request failed"}'
    return response


def test_ollama_generate(mock_env):
    response = make_response(
        {"response": "Hello from Ollama"}
    )

    with patch("requests.post", return_value=response) as post:
        client = LLMClient()
        result = client.generate("Say hello")

    assert result == "Hello from Ollama"

    args, kwargs = post.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"]["model"] == "qwen2.5:3b"
    assert kwargs["json"]["prompt"] == "Say hello"
    assert kwargs["json"]["stream"] is False
    assert kwargs["timeout"] == 60


def test_openai_compatible_generate(mock_env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "http://localhost:8000/v1",
    )
    monkeypatch.setenv("LLM_MODEL", "local-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    response = make_response({
        "choices": [
            {"message": {"content": "Hello from local API"}}
        ]
    })

    with patch("requests.post", return_value=response) as post:
        client = LLMClient()
        result = client.generate("Say hello")

    assert result == "Hello from local API"

    args, kwargs = post.call_args
    assert args[0] == (
        "http://localhost:8000/v1/chat/completions"
    )
    assert kwargs["json"]["model"] == "local-model"
    assert kwargs["json"]["messages"] == [
        {"role": "user", "content": "Say hello"}
    ]
    assert kwargs["json"]["stream"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_api_key_is_optional(mock_env):
    response = make_response({"response": "Hello"})

    with patch("requests.post", return_value=response) as post:
        client = LLMClient()
        client.generate("Say hello")

    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_ollama_stream(mock_env):
    response = make_response({})
    response.iter_lines.return_value = [
        json.dumps({"response": "Hello "}).encode(),
        json.dumps(
            {"response": "world", "done": True}
        ).encode(),
    ]

    with patch("requests.post", return_value=response) as post:
        client = LLMClient()
        result = "".join(client.stream("Say hello"))

    assert result == "Hello world"
    assert post.call_args.kwargs["json"]["stream"] is True
    assert post.call_args.kwargs["stream"] is True
    assert post.call_args.kwargs["timeout"] == 120


def test_openai_compatible_stream(mock_env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "http://localhost:8000/v1",
    )

    response = make_response({})
    response.iter_lines.return_value = [
        b'data: {"choices":[{"delta":{"content":"Hello "}}]}',
        b'data: {"choices":[{"delta":{"content":"world"}}]}',
        b"data: [DONE]",
    ]

    with patch("requests.post", return_value=response) as post:
        client = LLMClient()
        result = "".join(client.stream("Say hello"))

    assert result == "Hello world"
    assert post.call_args.kwargs["json"]["stream"] is True
    assert post.call_args.kwargs["stream"] is True
    assert post.call_args.args[0] == (
        "http://localhost:8000/v1/chat/completions"
    )


def test_invalid_provider_fails(mock_env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "invalid")

    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        LLMClient()


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (
            requests.exceptions.Timeout(),
            "LLM request timed out",
        ),
        (
            requests.exceptions.ConnectionError(),
            "LLM service is unavailable",
        ),
    ],
)
def test_generate_connection_errors(mock_env, exception, message):
    with patch("requests.post", side_effect=exception):
        client = LLMClient()

        with pytest.raises(RuntimeError, match=message):
            client.generate("test")


def test_rate_limit_returns_runtime_error(mock_env):
    response = make_http_error_response(429)

    with patch("requests.post", return_value=response):
        client = LLMClient()

        with pytest.raises(
            RuntimeError,
            match="LLM rate limit exceeded",
        ):
            client.generate("test")


def test_other_http_error_returns_runtime_error(mock_env):
    response = make_http_error_response(500)

    with patch("requests.post", return_value=response):
        client = LLMClient()

        with pytest.raises(
            RuntimeError,
            match="LLM API returned HTTP 500",
        ):
            client.generate("test")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"response": ""},
        {"response": "   "},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_missing_or_empty_response_fails(mock_env, payload):
    response = make_response(payload)

    with patch("requests.post", return_value=response):
        client = LLMClient()

        with pytest.raises(
            RuntimeError,
            match="LLM response text is missing",
        ):
            client.generate("test")


def test_generate_stream_alias(mock_env):
    response = make_response({})
    response.iter_lines.return_value = [
        json.dumps(
            {"response": "Hello", "done": True}
        ).encode(),
    ]

    with patch("requests.post", return_value=response):
        client = LLMClient()
        result = "".join(client.generate_stream("test"))

    assert result == "Hello"
