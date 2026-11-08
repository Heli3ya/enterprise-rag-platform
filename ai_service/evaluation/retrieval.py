"""
Retrieval used by the evaluation runner.

The evaluation must measure the *production* retrieval behaviour, so the
scoring formula here is an exact copy of ``api/services.py``:

* vector similarity from pgvector (cosine distance)
* PostgreSQL full-text keyword rank (``simple`` configuration, the same
  one used for the GIN index on ``DocumentChunk.content``)
* min-max normalisation of both, fused as ``0.7 * semantic + 0.3 * keyword``
* ``+0.2`` when the raw query appears verbatim in the chunk
* cross-encoder rerank of the top candidates

The only intentional difference is the tenant/department filter: it is
passed in explicitly because the evaluation runs without a Django user.
"""

import logging


logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
SUBSTRING_BONUS = 0.2

# How many fused candidates are sent to the cross-encoder.
RERANK_CANDIDATES = 5

# Chunks are truncated before reranking for the same reason as in the
# chat pipeline: the cross-encoder is quadratic in sequence length.
RERANK_CONTENT_LIMIT = 500


def _normalize(scores):
    if not scores:
        return {}

    values = list(scores.values())
    low = min(values)
    high = max(values)

    if high == low:
        return {key: 1.0 for key in scores}

    return {
        key: (value - low) / (high - low)
        for key, value in scores.items()
    }


def _vector_value(vector):
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _vector_search(cursor, query_vector, tenant_id, department_ids, limit):
    cursor.execute(
        """
        SELECT
            e.chunk_id,
            c.content,
            c.chunk_index,
            d.id AS document_id,
            d.title AS document_title,
            e.embedding_vector <=> %s::vector AS distance
        FROM documents_embedding AS e
        INNER JOIN documents_documentchunk AS c
            ON e.chunk_id = c.id
        INNER JOIN documents_document AS d
            ON c.document_id = d.id
        WHERE d.tenant_id = %s
          AND d.department_id = ANY(%s)
        ORDER BY e.embedding_vector <=> %s::vector
        LIMIT %s
        """,
        (
            query_vector,
            tenant_id,
            list(department_ids),
            query_vector,
            limit,
        ),
    )

    rows = []

    for row in cursor.fetchall():
        rows.append(
            {
                "chunk_id": row[0],
                "content": row[1],
                "chunk_index": row[2],
                "document_id": row[3],
                "document_title": row[4],
                "distance": float(row[5]),
            }
        )

    return rows


def _keyword_search(cursor, query, tenant_id, department_ids, limit):
    cursor.execute(
        """
        SELECT
            c.id,
            c.content,
            c.chunk_index,
            d.id AS document_id,
            d.title AS document_title,
            ts_rank(
                to_tsvector('simple', c.content),
                plainto_tsquery('simple', %s)
            ) AS rank
        FROM documents_documentchunk AS c
        INNER JOIN documents_document AS d
            ON c.document_id = d.id
        WHERE d.tenant_id = %s
          AND d.department_id = ANY(%s)
          AND to_tsvector('simple', c.content)
              @@ plainto_tsquery('simple', %s)
        ORDER BY rank DESC
        LIMIT %s
        """,
        (
            query,
            tenant_id,
            list(department_ids),
            query,
            limit,
        ),
    )

    return [
        {
            "chunk_id": row[0],
            "content": row[1],
            "chunk_index": row[2],
            "document_id": row[3],
            "document_title": row[4],
            "rank": float(row[5]),
        }
        for row in cursor.fetchall()
    ]


def retrieve(
    connection,
    query,
    *,
    tenant_id,
    department_ids,
    limit=5,
    embed_query=None,
    rerank=None,
):
    """
    Run the production hybrid retrieval for one question.

    ``embed_query`` maps the question to a vector; ``rerank`` maps
    ``(query, texts)`` to a list of float scores. Both are injected so
    the function stays testable without the model registry.
    """

    if not query or not query.strip():
        return []

    if tenant_id is None or not department_ids:
        raise ValueError(
            "tenant_id and at least one department id are required."
        )

    if embed_query is None:
        raise ValueError("embed_query callable is required.")

    query_vector = _vector_value(embed_query(query))
    candidate_limit = max(limit * 3, limit)

    with connection.cursor() as cursor:
        vector_rows = _vector_search(
            cursor,
            query_vector,
            tenant_id,
            department_ids,
            candidate_limit,
        )

        keyword_rows = _keyword_search(
            cursor,
            query,
            tenant_id,
            department_ids,
            candidate_limit,
        )

    semantic_scores = {
        row["chunk_id"]: 1.0 - row["distance"] for row in vector_rows
    }
    keyword_scores = {
        row["chunk_id"]: row["rank"] for row in keyword_rows
    }

    semantic_scores = _normalize(semantic_scores)
    keyword_scores = _normalize(keyword_scores)

    rows_by_id = {}

    for row in keyword_rows:
        rows_by_id[row["chunk_id"]] = row

    for row in vector_rows:
        rows_by_id.setdefault(row["chunk_id"], row)

    fused = []

    for chunk_id in set(semantic_scores) | set(keyword_scores):
        row = rows_by_id.get(chunk_id)

        if row is None:
            continue

        score = (
            SEMANTIC_WEIGHT * semantic_scores.get(chunk_id, 0.0)
            + KEYWORD_WEIGHT * keyword_scores.get(chunk_id, 0.0)
        )

        if query.lower() in (row["content"] or "").lower():
            score += SUBSTRING_BONUS

        fused.append(
            {
                "chunk_id": chunk_id,
                "content": row["content"],
                "chunk_index": row["chunk_index"],
                "document_id": row["document_id"],
                "document_title": row["document_title"],
                "score": score,
            }
        )

    fused.sort(key=lambda item: item["score"], reverse=True)
    candidates = fused[:RERANK_CANDIDATES]

    if rerank is not None and candidates:
        try:
            scores = rerank(
                query,
                [item["content"][:RERANK_CONTENT_LIMIT] for item in candidates],
            )

            if scores and len(scores) == len(candidates):
                for item, rerank_score in zip(candidates, scores):
                    item["rerank_score"] = float(rerank_score)

                candidates.sort(
                    key=lambda item: item["rerank_score"],
                    reverse=True,
                )
            else:
                logger.warning(
                    "Reranker returned %s scores for %s candidates; "
                    "falling back to hybrid order.",
                    len(scores or []),
                    len(candidates),
                )

        except Exception as exc:
            logger.warning(
                "Reranking unavailable during evaluation: %s",
                exc,
            )

    return candidates[:limit]


def format_contexts(results, max_chars=1200):
    """Plain text list of the retrieved chunks, in rank order."""

    return [
        (item.get("content") or "")[:max_chars]
        for item in results
        if (item.get("content") or "").strip()
    ]
