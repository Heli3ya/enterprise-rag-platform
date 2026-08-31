from fastapi import FastAPI
from pydantic import BaseModel, Field
from llm_client import LLMClient
from sentence_transformers import SentenceTransformer, CrossEncoder
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
class RerankRequest(BaseModel):
    query: str
    results: list[str] = Field(min_length=1)
class LLMRequest(BaseModel):
    prompt: str = Field(min_length=1)  
@app.get("/health")
def health_check():
    return {"status": "ok"}
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