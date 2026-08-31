from unittest.mock import patch
import requests

from llm_client import LLMClient


response = requests.Response()
response.status_code = 429
response._content = b'{"error": "rate limited"}'
response.url = "http://127.0.0.1:11434/api/generate"


with patch("requests.post", return_value=response):
    try:
        LLMClient().generate("test")
    except RuntimeError as exc:
        print(exc)