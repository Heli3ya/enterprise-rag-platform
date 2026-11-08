
import logging
import os
import re
import time
from types import SimpleNamespace

import requests
from django.conf import settings
from django.contrib.postgres.search import (
    SearchVector,
    SearchQuery,
    SearchRank,
)

from documents.models import DocumentChunk


logger = logging.getLogger(__name__)


# Score assigned to a result the reranker did not score. It sorts last
# and is JSON serializable (unlike -inf / -Infinity).
MISSING_RERANK_SCORE = -1e9


class AIServiceError(RuntimeError):
    """The AI inference service returned an error response."""


class AIServiceUnavailable(AIServiceError):
    """The AI inference service could not be reached at all."""


def ai_service_post(
    path,
    *,
    json=None,
    read_timeout=None,
    stream=False,
):
    """
    Call the AI inference service with sane timeouts and small retries.

    Connection problems are retried because the AI service often needs a
    moment to load its models. HTTP error responses are not retried,
    they are surfaced to the caller as AIServiceError.
    """

    url = f"{settings.AI_SERVICE_URL}{path}"
    connect_timeout = settings.AI_SERVICE_CONNECT_TIMEOUT
    read_timeout = read_timeout or settings.AI_SERVICE_READ_TIMEOUT
    attempts = max(1, settings.AI_SERVICE_MAX_RETRIES)

    # The AI service refuses callers that do not present the shared
    # secret, so reaching the port is no longer enough to query it.
    headers = {}

    if settings.AI_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = settings.AI_INTERNAL_TOKEN

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                url,
                json=json,
                headers=headers or None,
                timeout=(connect_timeout, read_timeout),
                stream=stream,
            )
            response.raise_for_status()

            return response

        except requests.exceptions.HTTPError as exc:
            # Response.__bool__ is False for 4xx/5xx, so an explicit
            # "is not None" check is required here.
            status_code = (
                exc.response.status_code
                if exc.response is not None
                else "?"
            )

            detail = ""

            if exc.response is not None:
                try:
                    payload = exc.response.json()

                    if isinstance(payload, dict):
                        raw_detail = (
                            payload.get("detail")
                            or payload.get("error")
                            or ""
                        )
                        detail = (
                            raw_detail
                            if isinstance(raw_detail, str)
                            else str(raw_detail)
                        )
                except Exception:
                    try:
                        detail = exc.response.text[:300]
                    except Exception:
                        detail = ""

            message = f"AI service error ({status_code})"

            if detail:
                message = f"{message}: {detail}"

            raise AIServiceError(message) from exc

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            last_error = exc

            logger.warning(
                "AI service call to %s failed (attempt %s/%s): %s",
                path,
                attempt,
                attempts,
                exc,
            )

            if attempt < attempts:
                time.sleep(
                    settings.AI_SERVICE_RETRY_BACKOFF * attempt,
                )

    raise AIServiceUnavailable(
        f"AI service is unavailable at {settings.AI_SERVICE_URL}. {last_error}"
    ) from last_error


def generate_embeddings(texts):
    response = ai_service_post(
        "/api/embed/",
        json={"texts": texts},
    )
    data = response.json()
    return data["embeddings"], data["dimension"]


def generate_query_embedding(query):
    response = ai_service_post(
        "/api/embed/",
        json={"texts": [query]},
    )
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
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    if getattr(user, "tenant_id", None) is None:
        return None

    return getattr(user, "department_id", None)


def semantic_search(query, limit=5, user=None):
    department_id = get_user_department_id(user)

    if department_id is None:
        return []

    tenant_id = user.tenant_id

    response = ai_service_post(
        "/api/vector-search/",
        json={
            "query": query,
            "tenant_id": tenant_id,
            "allowed_department_ids": [department_id],
            "limit": limit,
        },
    )
    data = response.json()

    returned_ids = [
        item["chunk_id"]
        for item in data.get("results", [])
        if "chunk_id" in item
    ]

    if not returned_ids:
        return []

    # AI service results are not trusted as the source of document content.
    # Verify every returned chunk against the authoritative Django database.
    authorized_chunks = (
        DocumentChunk.objects
        .select_related("document", "document__department")
        .filter(
            id__in=returned_ids,
            document__tenant_id=tenant_id,
            document__department_id=department_id,
            document__department__tenant_id=tenant_id,
        )
    )

    chunks_by_id = {
        chunk.id: chunk
        for chunk in authorized_chunks
    }

    results = []

    for item in data.get("results", []):
        chunk = chunks_by_id.get(item.get("chunk_id"))

        if chunk is None:
            continue

        document = SimpleNamespace(
            id=chunk.document_id,
            title=chunk.document.title,
            department_id=chunk.document.department_id,
        )

        authorized_chunk = SimpleNamespace(
            id=chunk.id,
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            document_id=chunk.document_id,
            document=document,
        )

        results.append(
            SimpleNamespace(
                chunk_id=chunk.id,
                distance=float(item["distance"]),
                chunk=authorized_chunk,
            )
        )

    return results


def keyword_search(query, limit=5, user=None):
    department_id = get_user_department_id(user)

    if department_id is None:
        return DocumentChunk.objects.none()

    tenant_id = user.tenant_id

    search_query = SearchQuery(
        query,
        config="simple",
    )

    return (
        DocumentChunk.objects
        .select_related("document", "document__department")
        .filter(
            document__tenant_id=tenant_id,
            document__department_id=department_id,
            document__department__tenant_id=tenant_id,
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

    response = ai_service_post(
        "/api/rerank/",
        json={
            "query": query,
            "results": rerank_contents,
        },
    )

    reranked_data = response.json()

    score_by_content = {
        item["content"]: float(item["score"])
        for item in reranked_data["results"]
    }

    reranked_results = []

    for result in results:
        rerank_content = result["content"][:max_content_length]
        # A missing score must sort last and stay JSON serializable, so a
        # very small number is used instead of -inf (which would produce
        # an invalid JSON payload such as -Infinity).
        rerank_score = score_by_content.get(
            rerank_content,
            MISSING_RERANK_SCORE,
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
    if get_user_department_id(user) is None:
        return []

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
        semantic_score = semantic_scores.get(chunk_id, 0.0)
        keyword_score = keyword_scores.get(chunk_id, 0.0)

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

    try:
        reranked_results = rerank_results(
            query,
            rerank_candidates,
        )
    except AIServiceError as exc:
        # The reranker is optional (it can be disabled on low memory
        # machines). Search must keep working, so the hybrid score is
        # used as the final score in that case.
        logger.warning(
            "Reranking unavailable, using hybrid scores instead: %s",
            exc,
        )

        reranked_results = [
            {
                **item,
                "rerank_score": item["score"],
            }
            for item in rerank_candidates
        ]

    return reranked_results[:limit]


# How many characters of each chunk reach the prompt.
#
# Prompt processing dominates the answer latency on a CPU-only host
# (~8 tokens/second with four cores), so the context is capped instead of
# being sent whole. 700 characters keeps the retrieved passage intact for
# typical chunks while bounding the worst case.
RAG_CONTEXT_CHARS = int(os.getenv("RAG_CONTEXT_CHARS", "700"))


def _prompt_excerpt(content):
    """Trim a chunk to the prompt budget, marking the cut."""

    text = (content or "").strip()

    if len(text) <= RAG_CONTEXT_CHARS:
        return text

    return text[:RAG_CONTEXT_CHARS].rstrip() + " …"


def build_rag_prompt(query, results):
    context_parts = []

    for result in results:
        context_parts.append(
            f"[{result['chunk_id']}]\n"
            f"{_prompt_excerpt(result['content'])}"
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


def build_citations(citation_ids, user=None):
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "tenant_id", None) is None
    ):
        return []

    chunks = (
        DocumentChunk.objects
        .select_related("document", "document__department")
        .filter(
            id__in=citation_ids,
            document__tenant_id=user.tenant_id,
            document__department__tenant_id=user.tenant_id,
        )
    )

    department_id = getattr(user, "department_id", None)

    if department_id is not None:
        chunks = chunks.filter(
            document__department_id=department_id,
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
                "title": document.title,
                "filename": document.file_path.name,
                "department": document.department.name,
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                # A short preview lets the UI show the cited passage
                # immediately, without an extra request.
                "snippet": chunk.content[:280],
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

    prompt = build_rag_prompt(query, results)

    response = ai_service_post(
        "/api/llm/",
        json={"prompt": prompt, "max_tokens": settings.LLM_MAX_TOKENS},
        read_timeout=settings.AI_SERVICE_LLM_READ_TIMEOUT,
    )

    data = response.json()
    answer = data.get("answer")

    if not answer:
        raise RuntimeError("LLM response text is missing")

    citations = build_citations(
        extract_citation_ids(answer),
        user=user,
    )

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

    prompt = build_rag_prompt(query, results)
    full_answer = ""

    response = ai_service_post(
        "/api/llm/stream/",
        json={"prompt": prompt, "max_tokens": settings.LLM_MAX_TOKENS},
        read_timeout=settings.AI_SERVICE_LLM_READ_TIMEOUT,
        stream=True,
    )

    with response:
        for chunk in response.iter_content(
            chunk_size=None,
            decode_unicode=False,
        ):
            if not chunk:
                continue

            # Decode explicitly: requests may otherwise guess
            # ISO-8859-1 and corrupt Persian text.
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")

            if not chunk:
                continue

            full_answer += chunk

            yield {
                "type": "token",
                "content": chunk,
            }

    citations = build_citations(
        extract_citation_ids(full_answer),
        user=user,
    )

    yield {
        "type": "citations",
        "citations": citations,
    }

    yield {
        "type": "done",
    }
