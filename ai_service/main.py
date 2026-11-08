import hmac
import os
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache

from dotenv import load_dotenv
import sentry_sdk
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from db import get_db_connection, release_db_connection
from evaluation.config import EvalConfig
from evaluation.dataset import DatasetError, dataset_summary, load_dataset
from evaluation.jobs import EvaluationBusy, JobRegistry, build_request
from evaluation.runner import EvaluationRunner
from evaluation.scheduler import EvaluationScheduler
from llm_client import LLMClient


# Load environment variables.
load_dotenv()

# Keep tokenizers single threaded, otherwise the small container sizes
# used for local deployments end up spawning dozens of threads.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Allow a fully offline deployment (models must already be cached).
if os.getenv("AI_OFFLINE", "0").strip().lower() in {"1", "true", "yes"}:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


SENTRY_FASTAPI_DSN = os.getenv("SENTRY_FASTAPI_DSN", "").strip()


def _before_send(event, hint):
    """
    Do not report expected dependency failures as errors.

    A 503 from /api/llm/* only means the language model is not running
    yet (or is intentionally disabled). That is an operational state,
    not a bug, and it must not page anyone.
    """

    exc_info = hint.get("exc_info")

    if exc_info:
        exc = exc_info[1]

        if isinstance(exc, StarletteHTTPException) and exc.status_code in {
            429,
            503,
        }:
            return None

    return event


if SENTRY_FASTAPI_DSN:
    sentry_sdk.init(
        dsn=SENTRY_FASTAPI_DSN,
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        send_default_pii=False,
        traces_sample_rate=0.1,
        before_send=_before_send,
    )


EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "intfloat/multilingual-e5-small",
)

RERANKER_MODEL_NAME = os.getenv(
    "RERANKER_MODEL_NAME",
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
)

# The reranker is optional. On memory constrained machines it can be
# disabled with AI_ENABLE_RERANKER=0, in that case the search falls back
# to the hybrid (vector + keyword) score.
ENABLE_RERANKER = os.getenv(
    "AI_ENABLE_RERANKER",
    "1",
).strip().lower() not in {"0", "false", "no"}

# How long an inference request waits for the models to finish loading.
MODEL_LOAD_TIMEOUT = float(os.getenv("AI_MODEL_LOAD_TIMEOUT", "180"))

# How many CPU threads torch is allowed to use.
TORCH_THREADS = int(os.getenv("AI_TORCH_THREADS", "2"))


@asynccontextmanager
def _warm_up_llm():
    """
    Load the LLM into Ollama before the first user question.

    Ollama loads the weights on the first request, which costs 10-25
    seconds on a CPU-only host. Doing it at startup moves that cost out
    of the first answer. Failures are ignored: the service stays usable
    and the next request simply pays the load.
    """

    try:
        models.wait_until_ready()

        llm_client.generate_with_options(
            "ping",
            max_tokens=1,
            temperature=0.0,
            timeout=120,
        )

        print("[ai_service] language model warmed up", flush=True)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[ai_service] warm-up skipped: {exc}", flush=True)


async def lifespan(_app):
    """
    Start the optional evaluation scheduler with the service.

    The scheduler is a plain daemon thread and does nothing unless
    AI_EVAL_SCHEDULE_HOURS is greater than zero.
    """

    try:
        eval_scheduler.start()
    except Exception as exc:  # pragma: no cover - startup safety
        print(f"[ai_service] evaluation scheduler failed to start: {exc}",
              flush=True)

    # Warm the LLM in the background so /health still answers instantly.
    threading.Thread(
        target=_warm_up_llm,
        name="llm-warmup",
        daemon=True,
    ).start()

    try:
        yield
    finally:
        try:
            eval_scheduler.stop()
        except Exception:  # pragma: no cover - shutdown safety
            pass


app = FastAPI(
    title="AI Inference Service",
    version="1.0.0",
    lifespan=lifespan,
)

# Keep inference concurrency bounded for low-memory machines.
inference_lock = threading.Semaphore(1)


class ModelRegistry:
    """
    Load the transformer models in the background.

    Loading the models used to happen while the module was imported, so
    the service could not answer /health until the models were ready.
    On slow or memory constrained machines that took minutes, which made
    the whole Docker stack look broken. Now the service starts
    immediately and reports its readiness through /health and /ready.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ready_event = threading.Event()

        self.embedding = None
        self.reranker = None

        self.embedding_status = "pending"
        self.reranker_status = "pending"
        self.error = None

    def load(self):
        try:
            try:
                import torch

                torch.set_num_threads(TORCH_THREADS)
            except Exception:
                pass

            from sentence_transformers import (
                SentenceTransformer,
                CrossEncoder,
            )

            self.embedding = SentenceTransformer(EMBEDDING_MODEL_NAME)
            self.embedding_status = "ready"

            if ENABLE_RERANKER:
                self.reranker = CrossEncoder(RERANKER_MODEL_NAME)
                self.reranker_status = "ready"
            else:
                self.reranker_status = "disabled"

            self.error = None

        except Exception as exc:
            self.embedding_status = "error"
            self.reranker_status = "error"
            self.error = str(exc)

            print(f"[ai_service] model loading failed: {exc}", flush=True)

        finally:
            self._ready_event.set()

    def start_background_load(self):
        thread = threading.Thread(
            target=self.load,
            name="model-loader",
            daemon=True,
        )
        thread.start()

        return thread

    @property
    def is_ready(self):
        return (
            self.embedding_status == "ready"
            and self.reranker_status in {"ready", "disabled"}
        )

    def status(self):
        with self._lock:
            return {
                "embedding": self.embedding_status,
                "reranker": self.reranker_status,
                "error": self.error,
            }

    def wait_until_ready(self, timeout=None):
        timeout = MODEL_LOAD_TIMEOUT if timeout is None else timeout

        if self.is_ready:
            return True

        self._ready_event.wait(timeout=timeout)

        return self.is_ready

    def get_embedding_model(self):
        if self.embedding_status == "error":
            raise HTTPException(
                status_code=503,
                detail=(
                    "The embedding model failed to load: "
                    f"{self.error}"
                ),
            )

        if self.embedding is None:
            if not self.wait_until_ready():
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The embedding model is still loading. "
                        "Please retry in a moment."
                    ),
                )

        return self.embedding

    def get_reranker_model(self):
        if not ENABLE_RERANKER:
            raise HTTPException(
                status_code=503,
                detail="The reranker is disabled on this deployment.",
            )

        if self.reranker_status == "error":
            raise HTTPException(
                status_code=503,
                detail=(
                    "The reranker model failed to load: "
                    f"{self.error}"
                ),
            )

        if self.reranker is None:
            if not self.wait_until_ready():
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The reranker model is still loading. "
                        "Please retry in a moment."
                    ),
                )

        return self.reranker


models = ModelRegistry()
models.start_background_load()

llm_client = LLMClient()


# ---------------------------------------------------------------------------
# RAG evaluation
# ---------------------------------------------------------------------------

eval_config = EvalConfig.from_env()
eval_jobs = JobRegistry(max_history=20)


def _build_embedder():
    def embed(texts):
        model = models.get_embedding_model()

        with inference_lock:
            vectors = model.encode(
                texts,
                batch_size=8,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

        return vectors.tolist()

    return embed


def _build_reranker():
    if not ENABLE_RERANKER:
        return None

    def rerank(query, texts):
        model = models.get_reranker_model()

        with inference_lock:
            scores = model.predict(
                [[query, text] for text in texts],
                show_progress_bar=False,
            )

        return [float(score) for score in scores]

    return rerank


def build_evaluation_runner():
    """Create a runner bound to the models already loaded in this process."""

    return EvaluationRunner(
        eval_config,
        llm_client=llm_client,
        embedder=_build_embedder(),
        embed_query=encode_query_cached,
        reranker=_build_reranker(),
        connection_factory=get_db_connection,
        connection_releaser=release_db_connection,
    )


eval_scheduler = EvaluationScheduler(
    eval_jobs,
    build_evaluation_runner,
    eval_config,
    is_ready=models.wait_until_ready,
)


def require_eval_token(x_eval_token: str = Header(default="")):
    """
    Gate the internal evaluation endpoints behind a shared secret.

    When AI_EVAL_TOKEN is empty the endpoints stay open, which is only
    acceptable because the service is not exposed publicly. Setting the
    token is strongly recommended outside a laptop.
    """

    if not eval_config.token:
        return

    if not hmac.compare_digest(x_eval_token, eval_config.token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing evaluation token.",
        )


INTERNAL_TOKEN = os.getenv("AI_INTERNAL_TOKEN", "").strip()


def require_internal_token(x_internal_token: str = Header(default="")):
    """
    Require the shared secret that Django sends on every inference call.

    Publishing port 8001 used to be enough to read any tenant's chunks,
    because the service trusted whoever could reach it. The token makes
    network access insufficient on its own.

    When AI_INTERNAL_TOKEN is empty the check is skipped so a bare local
    run keeps working; Compose always sets it.
    """

    if not INTERNAL_TOKEN:
        return

    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing internal token.",
        )


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class VectorSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    tenant_id: int = Field(gt=0)
    allowed_department_ids: list[int] = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    results: list[str] = Field(min_length=1, max_length=50)


class LLMRequest(BaseModel):
    prompt: str = Field(min_length=1)
    # Bounds the worst-case latency on CPU-only hosts. None keeps the
    # provider default, which is what the evaluation runner relies on.
    max_tokens: int | None = Field(default=None, ge=1, le=4096)
    temperature: float | None = Field(default=None, ge=0, le=2)


@lru_cache(maxsize=256)
def encode_query_cached(query: str) -> tuple[float, ...]:
    """Cache embeddings for repeated search queries."""
    model = models.get_embedding_model()

    with inference_lock:
        vector = model.encode(
            query,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    return tuple(float(value) for value in vector)


@app.get("/health")
def health_check():
    """
    Liveness probe.

    Always answers as long as the process is alive, even while the
    models are still loading in the background.
    """

    status = models.status()

    return {
        "status": "ok",
        "ready": models.is_ready,
        "models": status,
    }


@app.get("/ready")
def readiness_check():
    """Readiness probe, only successful once the models are loaded."""

    if not models.is_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "models": models.status(),
            },
        )

    return {
        "status": "ready",
        "models": models.status(),
    }


@app.get("/api/status/")
def service_status(_: None = Depends(require_internal_token)):
    """Detailed status, used to diagnose deployment problems."""

    database_status = "unknown"

    connection = None
    discard_connection = False

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()

        database_status = "connected"

    except Exception as exc:
        discard_connection = connection is not None
        database_status = f"error: {exc}"

    finally:
        if connection is not None:
            release_db_connection(
                connection,
                discard=discard_connection,
            )

    return {
        "status": "ok",
        "ready": models.is_ready,
        "models": models.status(),
        "database": database_status,
        "llm": {
            "provider": llm_client.provider,
            "model": llm_client.model,
            "base_url": llm_client.base_url,
        },
        "evaluation": eval_scheduler.status(),
    }


@app.get("/api/db/test/")
def test_database_connection(_: None = Depends(require_internal_token)):
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
def generate_embeddings(
    request: EmbeddingRequest,
    _: None = Depends(require_internal_token),
):
    model = models.get_embedding_model()

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
def vector_search(
    request: VectorSearchRequest,
    _: None = Depends(require_internal_token),
):
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
                WHERE d.tenant_id = %s
                  AND d.department_id = ANY(%s)
                ORDER BY e.embedding_vector <=> %s::vector
                LIMIT %s
                """,
                (
                    vector_value,
                    request.tenant_id,
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
            "tenant_id": request.tenant_id,
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
def rerank_results(
    request: RerankRequest,
    _: None = Depends(require_internal_token),
):
    reranker = models.get_reranker_model()

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
def generate_answer(
    request: LLMRequest,
    _: None = Depends(require_internal_token),
):
    try:
        response = llm_client.generate_with_options(
            request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The language model is unavailable: {exc}",
        ) from exc

    return {"answer": response}


@app.post("/api/llm/stream/")
def stream_answer(
    request: LLMRequest,
    _: None = Depends(require_internal_token),
):
    try:
        llm_client.check_available()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The language model is unavailable: {exc}",
        ) from exc

    def generate():
        try:
            for token in llm_client.stream(
                request.prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ):
                yield token
        except Exception as exc:
            # The response has already started, so the failure is only
            # reported through the log and the broken stream.
            print(f"[ai_service] LLM stream failed: {exc}", flush=True)

    return StreamingResponse(
        generate(),
        media_type="text/plain",
    )


# ---------------------------------------------------------------------------
# Internal evaluation endpoints
#
# These are meant for operators and schedulers, not for the public API.
# They are guarded by the optional AI_EVAL_TOKEN header.
# ---------------------------------------------------------------------------


class EvaluationRequest(BaseModel):
    tenant_id: int | None = Field(default=None, gt=0)
    department_ids: list[int] | None = None
    limit: int | None = Field(default=None, gt=0)
    sample_ids: list[str] | None = None
    metrics: list[str] | None = None
    top_k: int | None = Field(default=None, gt=0, le=50)


@app.post("/api/eval/run/", status_code=202)
def start_evaluation(
    payload: EvaluationRequest | None = Body(default=None),
    _: None = Depends(require_eval_token),
):
    """
    Start an evaluation run in the background.

    Returns immediately with a job id; poll ``/api/eval/jobs/{job_id}/``
    for progress. Only one run may be active at a time.
    """

    raw = payload.model_dump(exclude_none=True) if payload else None

    try:
        request = build_request(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope = request.resolve(eval_config)

    if scope["tenant_id"] is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "tenant_id is required. Pass it in the body or set "
                "AI_EVAL_TENANT_ID."
            ),
        )

    if not scope["department_ids"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "department_ids is required. Pass them in the body or set "
                "AI_EVAL_DEPARTMENT_IDS."
            ),
        )

    try:
        total_samples = len(load_dataset(scope["dataset_path"]))
    except DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        job = eval_jobs.start(
            build_evaluation_runner(),
            request,
            triggered_by="api",
        )
    except EvaluationBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "dataset_samples": total_samples,
        "scope": {
            "tenant_id": scope["tenant_id"],
            "department_ids": list(scope["department_ids"]),
            "metrics": list(scope["metrics"]),
            "limit": scope["limit"],
            "top_k": scope["top_k"],
        },
        "status_url": f"/api/eval/jobs/{job['job_id']}/",
    }


@app.get("/api/eval/jobs/")
def list_evaluation_jobs(
    limit: int = 20,
    _: None = Depends(require_eval_token),
):
    """Recent evaluation jobs, newest first."""

    return {
        "running": eval_jobs.is_running,
        "jobs": eval_jobs.list(limit=max(1, min(limit, 100))),
    }


@app.get("/api/eval/jobs/{job_id}/")
def get_evaluation_job(
    job_id: str,
    _: None = Depends(require_eval_token),
):
    job = eval_jobs.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown evaluation job: {job_id}",
        )

    return job


@app.get("/api/eval/jobs/{job_id}/report/")
def get_evaluation_report(
    job_id: str,
    _: None = Depends(require_eval_token),
):
    """The full JSON report of a finished run."""

    job = eval_jobs.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown evaluation job: {job_id}",
        )

    path = (job.get("report_paths") or {}).get("json")

    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="The report is not available yet.",
        )

    return FileResponse(
        path,
        media_type="application/json",
        filename=os.path.basename(path),
    )


@app.get("/api/eval/jobs/{job_id}/report.csv")
def get_evaluation_report_csv(
    job_id: str,
    _: None = Depends(require_eval_token),
):
    """The same report flattened to CSV, one row per sample."""

    job = eval_jobs.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown evaluation job: {job_id}",
        )

    path = (job.get("report_paths") or {}).get("csv")

    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="The report is not available yet.",
        )

    return FileResponse(
        path,
        media_type="text/csv",
        filename=os.path.basename(path),
    )


@app.get("/api/eval/dataset/")
def get_evaluation_dataset(_: None = Depends(require_eval_token)):
    """Describe the ground-truth dataset without running anything."""

    try:
        samples = load_dataset(eval_config.dataset_path)
    except DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return dataset_summary(samples)


@app.get("/api/eval/config/")
def get_evaluation_config(_: None = Depends(require_eval_token)):
    """Non-secret view of the evaluation configuration."""

    return {
        "backend": eval_config.backend,
        "metrics": list(eval_config.metrics),
        "top_k": eval_config.top_k,
        "judge_timeout": eval_config.judge_timeout,
        "thresholds": eval_config.thresholds(),
        "default_tenant_id": eval_config.default_tenant_id,
        "default_department_ids": list(eval_config.default_department_ids),
        "max_samples": eval_config.max_samples,
        "dataset_path": str(eval_config.dataset_path),
        "output_dir": str(eval_config.output_dir),
        "token_required": bool(eval_config.token),
        "schedule": eval_scheduler.status(),
    }
