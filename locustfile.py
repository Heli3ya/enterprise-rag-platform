
import os
import random

from locust import HttpUser, between, task


SEARCH_QUERIES = [
    "IT department technical documents",
    "employee policies and procedures",
    "document knowledge base",
    "enterprise search",
    "HR department documents",
]


class SearchUser(HttpUser):
    wait_time = between(0.5, 1.0)

    def on_start(self):
        token = os.getenv("LOCUST_ACCESS_TOKEN")

        if not token:
            raise RuntimeError(
                "LOCUST_ACCESS_TOKEN is not set."
            )

        self.client.headers.update(
            {"Authorization": f"Bearer {token}"}
        )

    @task
    def search(self):
        payload = {
            "query_text": random.choice(SEARCH_QUERIES),
            "top_k": 5,
        }

        with self.client.post(
            "/api/query/search/",
            json=payload,
            name="POST /api/query/search/",
            catch_response=True,
            timeout=15,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"Search failed: HTTP {response.status_code}"
                )
                return

            try:
                data = response.json()
            except ValueError:
                response.failure("Invalid JSON response.")
                return

            if not isinstance(data, dict):
                response.failure(
                    "Unexpected response format: expected an object."
                )
                return

            if data.get("query_text") != payload["query_text"]:
                response.failure(
                    "Response query_text does not match the request."
                )
                return

            results = data.get("results")

            if not isinstance(results, list):
                response.failure(
                    "Invalid response: results must be a list."
                )
                return

            for item in results:
                if not isinstance(item, dict):
                    response.failure(
                        "Invalid response: a result is not an object."
                    )
                    return

                required_fields = {
                    "chunk_id",
                    "document_id",
                    "document_title",
                    "score",
                    "content",
                }

                if not required_fields.issubset(item.keys()):
                    response.failure(
                        "Invalid response: result fields are missing."
                    )
                    return

            response.success()
