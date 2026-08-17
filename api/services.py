import requests


AI_SERVICE_URL = "http://127.0.0.1:8001"


def generate_embeddings(texts):
    response = requests.post(
        f"{AI_SERVICE_URL}/api/embed/",
        json={"texts": texts},
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return data["embeddings"], data["dimension"]