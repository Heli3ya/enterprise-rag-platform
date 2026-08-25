import requests
from django.conf import settings
from pgvector.django import CosineDistance
from documents.models import Embedding

def generate_embeddings(texts):
    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/embed/",
        json={"texts": texts},
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return data["embeddings"], data["dimension"]

def generate_query_embedding(query):
    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/embed/",
        json={"texts": [query]},
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    embeddings = data["embeddings"]

    if len(embeddings) != 1:
        raise ValueError(
            "Query embedding response must contain exactly one vector."
        )

    if data["dimension"] != 384:
        raise ValueError(
            "Query embedding dimension must be 384."
        )

    return embeddings[0]

def semantic_search(query, limit=5):
    query_vector = generate_query_embedding(query)

    results = (
        Embedding.objects
        .select_related("chunk__document")
        .annotate(
            distance=CosineDistance(
                "embedding_vector",
                query_vector,
            )
        )
        .order_by("distance")[:limit]
    )

    return results