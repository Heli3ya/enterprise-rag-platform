import requests
import re
from django.conf import settings
from pgvector.django import CosineDistance
from django.contrib.postgres.search import (
    SearchVector,
    SearchQuery,
    SearchRank,
)
from django.db import models
from types import SimpleNamespace
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

def get_user_department_id(user):
    if user is None or not user.is_authenticated:
        return None

    return user.department_id
def semantic_search(query, limit=5, user=None):
    if user is None or user.department_id is None:
        return []

    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/vector-search/",
        json={
            "query": query,
            "allowed_department_ids": [
                user.department_id
            ],
            "limit": limit,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    results = []

    for item in data.get("results", []):
        document = SimpleNamespace(
            id=item["document_id"],
            title=item["document_title"],
            department_id=item["department_id"],
        )

        chunk = SimpleNamespace(
            id=item["chunk_id"],
            content=item["content"],
            chunk_index=item["chunk_index"],
            document_id=item["document_id"],
            document=document,
        )

        result = SimpleNamespace(
            chunk_id=item["chunk_id"],
            distance=item["distance"],
            chunk=chunk,
        )

        results.append(result)

    return results
def keyword_search(query, limit=5, user=None):
    department_id = get_user_department_id(user)

    if department_id is None:
        return DocumentChunk.objects.none()

    search_query = SearchQuery(
        query,
        config="simple",
    )

    results = (
        DocumentChunk.objects
        .select_related("document")
        .filter(
            document__department_id=department_id
        )
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

    max_content_length = 500

    rerank_contents = [
        result["content"][:max_content_length]
        for result in results
    ]

    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/rerank/",
        json={
            "query": query,
            "results": rerank_contents,
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
        rerank_content = result["content"][:max_content_length]

        rerank_score = score_by_content.get(
            rerank_content,
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
def hybrid_search(query, limit=5, user=None):
    initial_limit = limit * 3

    semantic_results = list(
        semantic_search(
            query,
            limit=initial_limit,
            user=user,
        )
    )

    keyword_results = list(
        keyword_search(
            query,
            limit=initial_limit,
            user=user,
        )
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
    rerank_candidates = fused_results[:5]
    reranked_results = rerank_results(
        query,
        rerank_candidates,
    )
    return reranked_results[:limit]

def build_rag_prompt(query, results):
    context_parts = []

    for result in results:
        context_parts.append(
            f"[{result['chunk_id']}]\n"
            f"{result['content']}"
        )

    context = "\n\n".join(context_parts)

    return f"""
You are an enterprise document question-answering assistant.

Answer the user's question using ONLY the provided document context.

User question:
{query}

Document context:
{context}

Citation rules:
- Use the provided context only.
- After every sentence that relies on a document chunk, add the chunk ID in square brackets.
- Use the exact chunk ID provided in the context.
- Do not invent or modify citation IDs.
- If a sentence uses multiple chunks, cite all relevant IDs.
- Do not add citations for information that is not supported by the provided context.

Return only the answer with inline citations.
""".strip()

def extract_citation_ids(answer):
    return sorted(
        {
            int(citation_id)
            for citation_id in re.findall(r"\[(\d+)\]", answer)
        }
    )

def build_citations(citation_ids):
    chunks = (
        DocumentChunk.objects
        .select_related("document", "document__department")
        .filter(id__in=citation_ids)
    )

    chunks_by_id = {
        chunk.id: chunk
        for chunk in chunks
    }

    citations = []

    for citation_id in citation_ids:
        chunk = chunks_by_id.get(citation_id)

        if chunk is None:
            continue

        document = chunk.document

        citations.append(
            {
                "document_id": document.id,
                "filename": document.file_path.name,
                "department": document.department.name,
                "chunk_id": chunk.id,
            }
        )

    return citations

def generate_rag_answer(query, limit=5, user=None):
    results = hybrid_search(
        query,
        limit=limit,
        user=user,
    )

    if not results:
        return {
            "answer": "No relevant documents were found.",
            "citations": [],
        }

    prompt = build_rag_prompt(
        query,
        results,
    )

    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/generate/",
        json={
            "prompt": prompt,
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    answer = data.get("response")

    if not answer:
        raise RuntimeError(
            "LLM response text is missing"
        )

    citation_ids = extract_citation_ids(answer)

    citations = build_citations(citation_ids)

    return {
        "answer": answer,
        "citations": citations,
    }

def generate_rag_stream(query, limit=5, user=None):
    results = hybrid_search(
        query,
        limit=limit,
        user=user,
    )

    if not results:
        yield {
            "type": "error",
            "message": "No relevant documents were found.",
        }
        return

    prompt = build_rag_prompt(
        query,
        results,
    )

    response = requests.post(
        f"{settings.AI_SERVICE_URL}/api/generate/stream/",
        json={
            "prompt": prompt,
        },
        stream=True,
        timeout=120,
    )

    response.raise_for_status()

    full_answer = ""

    for chunk in response.iter_content(
        chunk_size=None,
        decode_unicode=True,
    ):
        if not chunk:
            continue

        full_answer += chunk

        yield {
            "type": "token",
            "content": chunk,
        }

    citation_ids = extract_citation_ids(full_answer)

    citations = build_citations(citation_ids)

    yield {
        "type": "citations",
        "citations": citations,
    }

    yield {
        "type": "done",
    }