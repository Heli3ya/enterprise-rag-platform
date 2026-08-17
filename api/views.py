from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView

from documents.models import DocumentChunk, Embedding
from .services import generate_embeddings


@api_view(["POST"])
def create_embeddings(request):
    chunk_ids = request.data.get("chunk_ids", [])

    if not chunk_ids:
        return Response(
            {"error": "chunk_ids is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    chunks = DocumentChunk.objects.filter(id__in=chunk_ids)

    if not chunks.exists():
        return Response(
            {"error": "No valid document chunks found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    texts = [chunk.content for chunk in chunks]

    try:
        embeddings, dimension = generate_embeddings(texts)
    except Exception as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    created_embeddings = []

    for chunk, vector in zip(chunks, embeddings):
        embedding = Embedding.objects.create(
            chunk=chunk,
            embedding_vector=vector,
            model_name="intfloat/multilingual-e5-small",
        )

        created_embeddings.append(
            {
                "id": embedding.id,
                "chunk_id": chunk.id,
                "dimension": dimension,
            }
        )

    return Response(
        {
            "embeddings": created_embeddings,
            "count": len(created_embeddings),
        },
        status=status.HTTP_201_CREATED,
    )