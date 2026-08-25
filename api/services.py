import requests
from django.conf import settings
from pgvector.django import CosineDistance
from django.contrib.postgres.search import (
    SearchVector,
    SearchQuery,
    SearchRank,
)
from documents.models import DocumentChunk, Embedding
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
def keyword_search(query, limit=5):
    search_query = SearchQuery(
        query,
        config="simple",
    )
    results = (
        DocumentChunk.objects
        .select_related("document")
        .annotate(
            search_vector=SearchVector(
                "content",
                config="simple",
            ),
        )
        .filter(search_vector=search_query)
        .annotate(
            rank=SearchRank(
                "search_vector",
                search_query,
            )
        )
        .order_by("-rank")[:limit]
    )
    return results
def normalize_scores(scores):
    if not scores:
        return {}
    min_score = min(scores.values())
    max_score = max(scores.values())
    if max_score == min_score:
        return {
            key: 1.0
            for key in scores
        }
    return {
        key: (score - min_score) / (max_score - min_score)
        for key, score in scores.items()
    }
def rerank_results(query, results):
    if not results:
        return []
    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/rerank/",
        json={
            "query": query,
            "results": [
                result["content"]
                for result in results
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    reranked_data = response.json()
    score_by_content = {
        item["content"]: float(item["score"])
        for item in reranked_data["results"]
    }
    reranked_results = []
    for result in results:
        rerank_score = score_by_content.get(
            result["content"],
            float("-inf"),
        )
        reranked_results.append(
            {
                **result,
                "rerank_score": rerank_score,
            }
        )
    reranked_results.sort(
        key=lambda item: item["rerank_score"],
        reverse=True,
    )
    return reranked_results

def hybrid_search(query, limit=5):
    initial_limit = limit * 3
    semantic_results = list(
        semantic_search(query, limit=initial_limit)
    )
    keyword_results = list(
        keyword_search(query, limit=initial_limit)
    )
    semantic_scores = {
        result.chunk_id: 1.0 - float(result.distance)
        for result in semantic_results
    }
    keyword_scores = {
        result.id: float(result.rank)
        for result in keyword_results
    }
    semantic_scores = normalize_scores(semantic_scores)
    keyword_scores = normalize_scores(keyword_scores)
    all_chunk_ids = set(semantic_scores) | set(keyword_scores)
    semantic_by_id = {
        result.chunk_id: result
        for result in semantic_results
    }
    keyword_by_id = {
        result.id: result
        for result in keyword_results
    }
    fused_results = []
    for chunk_id in all_chunk_ids:
        semantic_score = semantic_scores.get(
            chunk_id,
            0.0,
        )
        keyword_score = keyword_scores.get(
            chunk_id,
            0.0,
        )
        score = (
            0.7 * semantic_score
            + 0.3 * keyword_score
        )
        result = (
            semantic_by_id.get(chunk_id)
            or keyword_by_id.get(chunk_id)
        )
        content = (
            result.chunk.content
            if hasattr(result, "chunk")
            else result.content
        )
        if query.lower() in content.lower():
            score += 0.2
        fused_results.append(
            {
                "chunk_id": chunk_id,
                "score": score,
                "content": content,
                "result": result,
            }
        )
    fused_results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )
    reranked_results = rerank_results(
        query,
        fused_results,
    )
    return reranked_results[:limit]