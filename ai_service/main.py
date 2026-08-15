from fastapi import FastAPI
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

app = FastAPI(
    title="AI Inference Service",
    version="1.0.0",
)

model = SentenceTransformer("intfloat/multilingual-e5-small")


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


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