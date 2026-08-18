import requests
from django.conf import settings


def generate_embeddings(texts):
    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/embed/",
        json={"texts": texts},
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return data["embeddings"], data["dimension"]