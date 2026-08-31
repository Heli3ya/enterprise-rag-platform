import requests


class LLMClient:
    def __init__(self):
        self.base_url = "http://localhost:11434/api"
        self.model = "qwen2.5:3b"

    def generate(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
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

        if "response" not in data:
            raise RuntimeError("LLM response text is missing")

        return data["response"]