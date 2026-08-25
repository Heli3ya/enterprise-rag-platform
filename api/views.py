from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiResponse
from documents.models import DocumentChunk, Embedding
from .services import generate_embeddings , semantic_search , hybrid_search


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
 
@extend_schema(
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "example": "شرایط مرخصی استعلاجی",
                }
            },
            "required": ["query"],
        }
    },
    responses={
        200: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document_id": {"type": "integer"},
                            "document_title": {"type": "string"},
                            "chunk_id": {"type": "integer"},
                            "chunk_index": {"type": "integer"},
                            "distance": {"type": "number"},
                            "content": {"type": "string"},
                        },
                    },
                },
            },
        }
    },
)






@api_view(["POST"])
def semantic_search_view(request):
    query = request.data.get("query", "").strip()

    if not query:
        return Response(
            {"error": "query is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        results = hybrid_search(query, limit=5)
    except Exception as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(
    {
        "query": query,
        "results": [
            {
                "document_id": (
                    result["result"].chunk.document_id
                    if hasattr(result["result"], "chunk")
                    else result["result"].document_id
                ),
                "document_title": (
                    result["result"].chunk.document.title
                    if hasattr(result["result"], "chunk")
                    else result["result"].document.title
                ),
                "chunk_id": result["chunk_id"],
                "chunk_index": (
                    result["result"].chunk.chunk_index
                    if hasattr(result["result"], "chunk")
                    else result["result"].chunk_index
                ),
                "score": round(float(result["score"]), 6),
                "content": result["content"],
            }
            for result in results
        ],
    },
    status=status.HTTP_200_OK,
)