
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

    def check_available(self, timeout: int = 5) -> None:
        """
        Verify that the configured LLM endpoint is reachable.

        This is called before a streaming response is started, so an
        unreachable LLM is reported as a proper HTTP error instead of a
        broken stream.
        """

        if self.provider == "ollama":
            url = f"{self.base_url}/tags"
        else:
            url = f"{self.base_url}/models"

        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=timeout,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                "LLM service did not answer in time"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"LLM service is unavailable at {self.base_url}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(
                f"LLM API returned HTTP {exc.response.status_code}"
            ) from exc

    def generate(self, prompt: str) -> str:
        return self.generate_with_options(prompt)

    def generate_with_options(
        self,
        prompt: str,
        *,
        temperature=None,
        max_tokens=None,
        timeout=None,
        seed=None,
    ) -> str:
        """
        Single-shot completion with explicit decoding options.

        ``generate`` is a thin wrapper around this method; the extra
        parameters are only sent when they are provided, so the payload
        for the chat endpoint stays byte-for-byte identical.
        """

        if self.provider == "ollama":
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }

            options = {}

            if temperature is not None:
                options["temperature"] = float(temperature)

            if max_tokens is not None:
                options["num_predict"] = int(max_tokens)

            if seed is not None:
                options["seed"] = int(seed)

            if options:
                payload["options"] = options

        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
            }

            if temperature is not None:
                payload["temperature"] = float(temperature)

            if max_tokens is not None:
                payload["max_tokens"] = int(max_tokens)

            if seed is not None:
                payload["seed"] = int(seed)

        try:
            response = requests.post(
                self._url("generate"),
                json=payload,
                headers=self._headers(),
                timeout=timeout or 60,
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

    def stream(self, prompt: str, *, max_tokens=None, temperature=None):
        """
        Stream a completion token by token.

        `max_tokens` bounds the answer length: on a CPU-only host an
        unbounded answer can stream for minutes, so the caller caps it.
        """

        if self.provider == "ollama":
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
            }

            options = {}

            if temperature is not None:
                options["temperature"] = float(temperature)

            if max_tokens is not None:
                options["num_predict"] = int(max_tokens)

            if options:
                payload["options"] = options
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": True,
            }

            if temperature is not None:
                payload["temperature"] = float(temperature)

            if max_tokens is not None:
                payload["max_tokens"] = int(max_tokens)

        try:
            with requests.post(
                self._url("generate"),
                json=payload,
                headers=self._headers(),
                stream=True,
                timeout=(10, 360),
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines(decode_unicode=False):
                    if not line:
                        continue

                    # Decode explicitly as UTF-8. requests guesses
                    # ISO-8859-1 when the server omits the charset,
                    # which corrupts Persian/Arabic text.
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")

                    if self.provider == "ollama":
                        data = json.loads(line)
                        chunk = data.get("response", "")

                        if chunk:
                            yield chunk

                        if data.get("done", False):
                            break
                    else:
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
