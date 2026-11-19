
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
from documents.versioning import ARCHIVED_STATUS


logger = logging.getLogger(__name__)


# Score assigned to a result the reranker did not score. It sorts last
# and is JSON serializable (unlike -inf / -Infinity).
MISSING_RERANK_SCORE = -1e9


# Absolute relevance floors.
#
# The fused score below is normalized per query, so the best result of
# any query is always 1.0 — it says "best of this query", never
# "relevant". A threshold on it therefore cannot tell "nothing matches"
# from "the best of a bad lot", and without a second, absolute signal the
# least irrelevant chunk is handed to the model, which then answers from
# it. These floors are compared against a raw score, which keeps its
# meaning across queries.
#
# Calibration on the models this project ships (multilingual-e5-small +
# cross-encoder), measured through this pipeline:
#
#   relevant, exact          +6.59     relevant, paraphrase (fa)  +1.10
#   relevant, cross-lingual  +5.56     relevant, paraphrase (fa)  -0.35
#   irrelevant, off-topic    -2.13     irrelevant, off-topic      -2.18
#   irrelevant, off-topic    -3.56     irrelevant, off-topic      -5.46
#
# The gap to protect is -0.35 (a real paraphrase) to -2.13 (the best
# irrelevant match). -1.0 sits inside it with a logit of margin on each
# side. A stricter 0.0 drops the cross-lingual paraphrase, and this is a
# Persian-first product: losing a real answer is worse than the risk the
# floor exists to remove.
RAG_MIN_RERANK_SCORE = float(
    os.getenv("RAG_MIN_RERANK_SCORE", "-1.0")
)

# The reranker is optional and can be switched off on a small host. When
# it is, no absolute signal is left: raw cosine similarities of
# multilingual-e5-small are compressed (0.71-0.92 on our own corpus), so
# a floor that drops an irrelevant passage also drops a relevant
# paraphrase. The default keeps the pre-existing behaviour; raise it only
# after measuring on your own documents.
RAG_MIN_SEMANTIC_SIMILARITY = float(
    os.getenv("RAG_MIN_SEMANTIC_SIMILARITY", "0.0")
)


# --- Cold start -------------------------------------------------------
#
# A department can be brand new, or simply have nothing about a given
# topic. Both cases must end in an honest "I have nothing to answer
# from" instead of a confident hallucination, and neither may cost an
# LLM call. The two reasons are kept apart because the UI acts on them
# differently: an empty department needs an upload prompt, a miss on a
# populated one only needs a rephrasing hint.
EMPTY_DEPARTMENT = "empty_department"
NO_MATCHING_CHUNKS = "no_match"

# Returned by the API so non-browser clients (curl, Swagger, the
# evaluation harness) still get a readable sentence. The frontend keys
# its own copy off `reason`, so this string is a fallback, not the UI
# text.
NO_DOCUMENTS_MESSAGE = (
    "در حال حاضر سندی مرتبط با این موضوع در دپارتمان شما یافت نشد"
)


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


def department_has_searchable_content(user):
    """
    Answer "could this department possibly answer anything?" from Postgres.

    This is the cold-start gate and it runs *before* the embedding call.
    A brand-new department would otherwise pay for a query embedding, a
    vector round-trip, a rerank and a generation pass, only to be told
    that there was nothing to read. One `EXISTS ... LIMIT 1` against an
    indexed foreign key costs a fraction of a millisecond and skips the
    whole pipeline.

    The check looks at chunks rather than documents on purpose: a
    document that is still Pending has no chunks, so it cannot answer
    anything yet, and the user should be told exactly that.
    """

    department_id = get_user_department_id(user)

    if department_id is None:
        return False

    return DocumentChunk.objects.filter(
        document__tenant_id=user.tenant_id,
        document__department_id=department_id,
        document__department__tenant_id=user.tenant_id,
        is_active=True,
    ).exclude(
        # A department whose only document has been superseded has
        # nothing to answer from, exactly like an empty one. The gate
        # must agree with the retrieval filter, or it would wave the
        # request through to an LLM that has no sources.
        document__status=ARCHIVED_STATUS,
    ).exists()


def _no_documents(reason):
    """Build the single, canonical "nothing to answer from" payload."""

    return {
        "answer": NO_DOCUMENTS_MESSAGE,
        "citations": [],
        "no_documents": True,
        "reason": reason,
    }


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
            is_active=True,
        )
        # Defence in depth: archiving drops the vectors, so the AI
        # service should not return these ids at all. Checking here
        # means a stale vector, a restored backup or a race still
        # cannot make an obsolete procedure citable.
        .exclude(document__status=ARCHIVED_STATUS)
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
            is_active=True,
        )
        .exclude(document__status=ARCHIVED_STATUS)
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

    # A 200 whose body is not the agreed shape is a contract violation,
    # not a ranking. Raising the same error as an HTTP failure keeps a
    # single fallback path in `hybrid_search`: an `AIServiceError` there
    # means "search anyway, on hybrid scores", whereas a KeyError would
    # reach the user as a 500 from `/api/search/`.
    items = (
        reranked_data.get("results")
        if isinstance(reranked_data, dict)
        else None
    )

    if not isinstance(items, list):
        raise AIServiceError(
            "The reranker returned an unexpected payload."
        )

    score_by_content = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        content = item.get("content")
        score = item.get("score")

        if not isinstance(content, str) or score is None:
            continue

        try:
            score_by_content[content] = float(score)
        except (TypeError, ValueError):
            continue

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

    semantic_similarities = {
        result.chunk_id: 1.0 - float(result.distance)
        for result in semantic_results
    }

    # Kept untouched for the relevance floor at the end: normalizing is
    # what makes the ranking work, and also what destroys the absolute
    # meaning of the number.
    semantic_scores = normalize_scores(semantic_similarities)

    keyword_scores = {
        result.id: float(result.rank)
        for result in keyword_results
    }

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
                # The raw similarity survives normalization only to be
                # used as a fallback relevance signal when the reranker
                # is unavailable.
                "semantic_similarity": semantic_similarities.get(
                    chunk_id,
                    0.0,
                ),
            }
        )

    fused_results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    rerank_candidates = fused_results[:5]
    reranked_by_model = True

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

        reranked_by_model = False

        reranked_results = [
            {
                **item,
                "rerank_score": item["score"],
            }
            for item in rerank_candidates
        ]

    # The floor. Everything above ranks; this decides whether anything
    # is worth answering from at all. The two scores are not
    # interchangeable — a cross-encoder score is a relevance logit, the
    # fallback is a cosine similarity — so each path uses its own knob.
    if reranked_by_model:
        score_key = "rerank_score"
        floor = RAG_MIN_RERANK_SCORE
    else:
        score_key = "semantic_similarity"
        floor = RAG_MIN_SEMANTIC_SIMILARITY

    # A literal hit is never irrelevant.
    #
    # The cross-encoder is trained mostly on English prose and scores a
    # Persian table row like `| بلبرینگ | 45 | یورو |` at −1.25 even
    # when the user typed a word that is *in* the row. Applying the
    # floor to that answer produces "nothing in your knowledge base
    # matched" for a query the corpus obviously contains — the worst
    # possible reply, because it is confidently wrong about its own
    # content. The length guard keeps a two-letter query from exempting
    # everything it happens to appear in.
    literal = (query or "").strip().casefold()

    def is_literal_hit(item):
        return (
            len(literal) >= 3
            and literal in (item.get("content") or "").casefold()
        )

    kept = [
        item
        for item in reranked_results
        if item.get(score_key, 0.0) >= floor or is_literal_hit(item)
    ]

    if reranked_results and not kept:
        # Nothing cleared the floor: the caller turns an empty list into
        # "no documents found", which is the honest answer. Answering
        # from the least irrelevant chunk is how a RAG system invents
        # sources.
        logger.info(
            "No result cleared the relevance floor: best %s %.3f, "
            "floor %.3f, dropped %s.",
            score_key,
            max(
                item.get(score_key, 0.0)
                for item in reranked_results
            ),
            floor,
            len(reranked_results),
        )

    rescued = sum(
        1
        for item in kept
        if item.get(score_key, 0.0) < floor
    )

    if rescued:
        logger.info(
            "Kept %s result(s) below the %s floor because the query "
            "appears verbatim in the text.",
            rescued,
            score_key,
        )

    return kept[:limit]


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

    # The answer-language rule is language-agnostic on purpose: it names
    # no language, so a new UI language needs no code change here, and
    # the prompt stays byte-identical to the evaluation copy (see
    # tests/test_eval_prompt_parity.py). Detecting the language on the
    # server was the alternative; it would have to be duplicated in two
    # containers and would still leave the model free to ignore the hint.
    #
    # The formatting rules exist because the renderer is deliberately a
    # small subset of Markdown (frontend/lib/answerFormat.ts). Asking for
    # plain prose keeps the two in agreement instead of relying on the
    # renderer to clean up whatever the model invents.
    return f"""
You are an enterprise document question-answering assistant.

Answer the user's question using ONLY the provided document context.

User question:
{query}

Document context:
{context}

Answer rules:
- Answer in the language of the user question. A Persian question must get a Persian answer even when the documents are in English, and an English question must get an English answer.
- Use the punctuation of that language (for Persian: ، ؛ ؟) and copy numbers, codes, IDs, prices, dates and names from the context exactly as they are written there. Never translate, convert or reorder digits.
- Write plain text. Do not use Markdown: no headings (#), no bold (**), no tables, no code blocks, no horizontal rules.
- Be brief: two to four complete sentences, or a "- " bullet list when the answer is genuinely a list of items.

Citation rules:
- Use the provided context only.
- After every sentence that relies on a document chunk, add the chunk ID in square brackets.
- Use the exact chunk ID provided in the context.
- Write the citation ID in Latin digits, exactly as it appears in the context: [66], not [۶۶].
- Do not invent or modify citation IDs.
- If a sentence uses multiple chunks, cite all relevant IDs.
- Do not add citations for information that is not supported by the provided context.
- Put the marker at the end of the sentence, right after the last word and before the final punctuation.
- Example: "مرخصی سالانه ۲۰ روز است [66]." / "Annual leave is 20 days [66]."

Return only the answer with inline citations.
""".strip()


# The answer-language rule asks for Persian digits, and a model applies
# it to the citation marker too: a Persian answer can cite `[۶۶]`. The
# id is a database integer, so it is normalized before lookup. Python's
# `\d` already matches these digits and `int()` accepts them, but doing
# it explicitly keeps the contract visible and independent of both.
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def extract_citation_ids(answer):
    normalized = (answer or "").translate(_DIGIT_TRANSLATION)

    return sorted(
        {
            int(citation_id)
            for citation_id in re.findall(r"\[(\d+)\]", normalized)
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
    # Cold start: stop before any network call. See
    # department_has_searchable_content() for why this is a chunk probe.
    if not department_has_searchable_content(user):
        return _no_documents(EMPTY_DEPARTMENT)

    results = hybrid_search(
        query,
        limit=limit,
        user=user,
    )

    if not results:
        return _no_documents(NO_MATCHING_CHUNKS)

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
        "no_documents": False,
        "reason": None,
    }


def generate_rag_stream(query, limit=5, user=None):
    # Same gate as generate_rag_answer, but it must not raise: the
    # caller has already committed to a 200 text/event-stream response.
    #
    # Every branch ends with `done`. The client uses that event to stop
    # its spinner, so an unterminated stream would leave the UI stuck on
    # "thinking" forever — the exact opposite of the cold-start goal.
    if not department_has_searchable_content(user):
        yield {
            "type": "no_documents",
            "reason": EMPTY_DEPARTMENT,
            "message": NO_DOCUMENTS_MESSAGE,
        }
        yield {"type": "done"}
        return

    results = hybrid_search(
        query,
        limit=limit,
        user=user,
    )

    if not results:
        yield {
            "type": "no_documents",
            "reason": NO_MATCHING_CHUNKS,
            "message": NO_DOCUMENTS_MESSAGE,
        }
        yield {"type": "done"}
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
