import os

from dotenv import load_dotenv
import sentry_sdk
from fastapi import FastAPI
from pydantic import BaseModel, Field
from llm_client import LLMClient
from db import get_db_connection
from fastapi.responses import StreamingResponse
from sentence_transformers import SentenceTransformer, CrossEncoder

# Load environment variables from the project root.
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

# Embedding model
model = SentenceTransformer("intfloat/multilingual-e5-small")

# Lightweight Cross-Encoder for reranking
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
    query: str
    results: list[str] = Field(min_length=1)


class LLMRequest(BaseModel):
    prompt: str = Field(min_length=1)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/db/test/")
def test_database_connection():
    connection = None

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

    finally:
        if connection is not None:
            connection.close()


@app.post("/api/embed/")
def generate_embeddings(request: EmbeddingRequest):
    embeddings = model.encode(
        request.texts,
        batch_size=8,
        show_progress_bar=False,
    )
    return {
        "embeddings": embeddings.tolist(),
        "dimension": model.get_embedding_dimension(),
    }


@app.post("/api/vector-search/")
def vector_search(request: VectorSearchRequest):
    query_vector = model.encode(
        request.query,
        show_progress_bar=False,
    ).tolist()

    vector_value = (
        "["
        + ",".join(str(value) for value in query_vector)
        + "]"
    )

    connection = None

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

    finally:
        if connection is not None:
            connection.close()


@app.post("/api/rerank/")
def rerank_results(request: RerankRequest):
    pairs = [[request.query, result] for result in request.results]
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
                "content": content,
                "score": float(score),
            }
            for content, score in reranked
        ],
    }


@app.post("/api/generate/")
def generate_text(request: LLMRequest):
    return {
        "response": llm_client.generate(request.prompt),
    }


@app.post("/api/generate/stream/")
def generate_text_stream(request: LLMRequest):
    def stream_response():
        for chunk in llm_client.generate_stream(request.prompt):
            yield chunk

    return StreamingResponse(
        stream_response(),
        media_type="text/plain",
    )


@app.get("/api/stream/test/")
def test_stream():
    def event_stream():
        yield "event: token\n"
        yield 'data: {"content": "Hello"}\n\n'

        yield "event: token\n"
        yield 'data: {"content": " from"}\n\n'

        yield "event: token\n"
        yield 'data: {"content": " SSE"}\n\n'

        yield "event: done\n"
        yield "data: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
