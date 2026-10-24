
import json
import os

import requests


class LLMClient:
    def __init__(self):
        self.provider = os.getenv(
            "LLM_PROVIDER",
            "ollama",
        ).strip().lower()

        if self.provider not in {
            "ollama",
            "openai_compatible",
        }:
            raise ValueError(
                "LLM_PROVIDER must be 'ollama' "
                "or 'openai_compatible'"
            )

        default_url = (
            "http://localhost:11434/api"
            if self.provider == "ollama"
            else "http://localhost:8000/v1"
        )

        self.base_url = os.getenv(
            "LLM_BASE_URL",
            default_url,
        ).rstrip("/")

        self.model = os.getenv(
            "LLM_MODEL",
            "qwen2.5:3b",
        )

        self.api_key = os.getenv("LLM_API_KEY", "").strip()

    def _headers(self):
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def _url(self, endpoint):
        if self.provider == "ollama":
            return f"{self.base_url}/{endpoint}"

        return f"{self.base_url}/chat/completions"

    def generate(self, prompt: str) -> str:
        if self.provider == "ollama":
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
            }

        try:
            response = requests.post(
                self._url("generate"),
                json=payload,
                headers=self._headers(),
                timeout=60,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout as exc:
            raise RuntimeError("LLM request timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError("LLM service is unavailable") from exc
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 429:
                raise RuntimeError("LLM rate limit exceeded") from exc
            raise RuntimeError(
                f"LLM API returned HTTP {response.status_code}"
            ) from exc

        data = response.json()

        if self.provider == "ollama":
            answer = data.get("response")
        else:
            choices = data.get("choices", [])
            answer = (
                choices[0].get("message", {}).get("content")
                if choices
                else None
            )

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("LLM response text is missing")

        return answer

    def stream(self, prompt: str):
        if self.provider == "ollama":
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
            }
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": True,
            }

        try:
            with requests.post(
                self._url("generate"),
                json=payload,
                headers=self._headers(),
                stream=True,
                timeout=120,
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue

                    if self.provider == "ollama":
                        data = json.loads(line)
                        chunk = data.get("response", "")

                        if chunk:
                            yield chunk

                        if data.get("done", False):
                            break
                    else:
                        if isinstance(line, bytes):
                            line = line.decode("utf-8")

                        if not line.startswith("data:"):
                            continue

                        data_text = line[5:].strip()

                        if data_text == "[DONE]":
                            break

                        data = json.loads(data_text)
                        choices = data.get("choices", [])

                        if choices:
                            chunk = (
                                choices[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if chunk:
                                yield chunk

        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                "LLM streaming request timed out"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError("LLM service is unavailable") from exc
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(
                f"LLM API returned HTTP {exc.response.status_code}"
            ) from exc

    def generate_stream(self, prompt: str):
        yield from self.stream(prompt)
