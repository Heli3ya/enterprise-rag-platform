from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiResponse
from documents.models import DocumentChunk, Embedding ,  SearchQuery,QueryResult
from .services import generate_embeddings , semantic_search , hybrid_search
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from django.db import transaction
from .services import generate_rag_answer
from .serializers import SearchQuerySerializer

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

@extend_schema(
    request=SearchQuerySerializer,
    responses=OpenApiResponse(
        description="Search results",
    ),
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def search_query_view(request):
    serializer = SearchQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    query_text = serializer.validated_data["query_text"]
    top_k = serializer.validated_data["top_k"]

    try:
        results = hybrid_search(
            query_text,
            limit=top_k,
            user = request.user,
        )
    except Exception as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    with transaction.atomic():
        search_query = SearchQuery.objects.create(
            user=request.user,
            query_text=query_text,
        )

        QueryResult.objects.bulk_create(
            [
                QueryResult(
                    query=search_query,
                    chunk_id=result["chunk_id"],
                    relevance_score=float(result["rerank_score"]),
                )
                for result in results
            ]
        )
    return Response(
        {
            "query_text": query_text,
            "results": [
                {
                    "chunk_id": result["chunk_id"],
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
                    "score": round(
                        float(result["rerank_score"]),
                        6,
                    ),
                    "content": result["content"],
                }
                for result in results
            ],
        },
        status=status.HTTP_200_OK,
    )
@extend_schema(
    request=SearchQuerySerializer,
    responses=OpenApiResponse(
        description="RAG answer with citations",
    ),
)
@api_view(["POST"])
def rag_query_view(request):
    serializer = SearchQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    query_text = serializer.validated_data["query_text"]
    top_k = serializer.validated_data["top_k"]

    try:
        result = generate_rag_answer(
            query_text,
            limit=top_k,
            user=request.user,
        )
    except Exception as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(
        {
            "query_text": query_text,
            "answer": result["answer"],
            "citations": result["citations"],
        },
        status=status.HTTP_200_OK,
    )