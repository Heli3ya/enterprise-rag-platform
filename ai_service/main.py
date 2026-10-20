
import os
import threading
from functools import lru_cache

from dotenv import load_dotenv
import sentry_sdk
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer, CrossEncoder

from db import get_db_connection, release_db_connection
from llm_client import LLMClient


# Load environment variables.
load_dotenv()

SENTRY_FASTAPI_DSN = os.getenv("SENTRY_FASTAPI_DSN", "").strip()

if SENTRY_FASTAPI_DSN:
    sentry_sdk.init(
        dsn=SENTRY_FASTAPI_DSN,
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        send_default_pii=False,
        traces_sample_rate=0.1,
    )


app = FastAPI(
    title="AI Inference Service",
    version="1.0.0",
)

# Keep inference concurrency bounded for low-memory machines.
inference_lock = threading.Semaphore(1)

# Load each model only once per service process.
model = SentenceTransformer("intfloat/multilingual-e5-small")
reranker = CrossEncoder(
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)
llm_client = LLMClient()


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class VectorSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    allowed_department_ids: list[int] = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    results: list[str] = Field(min_length=1, max_length=50)


class LLMRequest(BaseModel):
    prompt: str = Field(min_length=1)


@lru_cache(maxsize=256)
def encode_query_cached(query: str) -> tuple[float, ...]:
    """Cache embeddings for repeated search queries."""
    with inference_lock:
        vector = model.encode(
            query,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    return tuple(float(value) for value in vector)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/db/test/")
def test_database_connection():
    connection = None
    discard_connection = False

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            result = cursor.fetchone()

        return {
            "status": "ok",
            "database": "connected",
            "result": result[0],
        }

    except Exception:
        discard_connection = connection is not None
        raise

    finally:
        if connection is not None:
            release_db_connection(
                connection,
                discard=discard_connection,
            )


@app.post("/api/embed/")
def generate_embeddings(request: EmbeddingRequest):
    with inference_lock:
        embeddings = model.encode(
            request.texts,
            batch_size=8,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    return {
        "embeddings": embeddings.tolist(),
        "dimension": model.get_embedding_dimension(),
    }


@app.post("/api/vector-search/")
def vector_search(request: VectorSearchRequest):
    query_vector = encode_query_cached(request.query)

    vector_value = "[" + ",".join(
        str(value) for value in query_vector
    ) + "]"

    connection = None
    discard_connection = False

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    e.chunk_id,
                    c.content,
                    c.chunk_index,
                    d.id AS document_id,
                    d.title AS document_title,
                    d.department_id,
                    e.embedding_vector <=> %s::vector AS distance
                FROM documents_embedding AS e
                INNER JOIN documents_documentchunk AS c
                    ON e.chunk_id = c.id
                INNER JOIN documents_document AS d
                    ON c.document_id = d.id
                WHERE d.department_id = ANY(%s)
                ORDER BY e.embedding_vector <=> %s::vector
                LIMIT %s
                """,
                (
                    vector_value,
                    request.allowed_department_ids,
                    vector_value,
                    request.limit,
                ),
            )

            rows = cursor.fetchall()

        results = [
            {
                "chunk_id": row[0],
                "content": row[1],
                "chunk_index": row[2],
                "document_id": row[3],
                "document_title": row[4],
                "department_id": row[5],
                "distance": float(row[6]),
            }
            for row in rows
        ]

        return {
            "query": request.query,
            "allowed_department_ids": request.allowed_department_ids,
            "results": results,
        }

    except Exception:
        discard_connection = connection is not None
        raise

    finally:
        if connection is not None:
            release_db_connection(
                connection,
                discard=discard_connection,
            )


@app.post("/api/rerank/")
def rerank_results(request: RerankRequest):
    pairs = [
        [request.query, result[:500]]
        for result in request.results
    ]

    with inference_lock:
        scores = reranker.predict(
            pairs,
            show_progress_bar=False,
        )

    reranked = sorted(
        zip(request.results, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    return {
        "query": request.query,
        "results": [
            {
                "content": result,
                "score": float(score),
            }
            for result, score in reranked
        ],
    }


@app.post("/api/llm/")
def generate_answer(request: LLMRequest):
    response = llm_client.generate(request.prompt)
    return {"answer": response}


@app.post("/api/llm/stream/")
def stream_answer(request: LLMRequest):
    def generate():
        for token in llm_client.stream(request.prompt):
            yield token

    return StreamingResponse(
        generate(),
        media_type="text/plain",
    )
