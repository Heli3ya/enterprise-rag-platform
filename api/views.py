from rest_framework.decorators import api_view, throttle_classes
from .throttles import ChatUserRateThrottle
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework import status
from api.models import AuditLog
from api.serializers import AuditLogSerializer
from django.db.models import Sum, Count
from departments.models import Department
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiResponse
from documents.models import Document, DocumentChunk, Embedding, SearchQuery, QueryResult
from .services import generate_embeddings , semantic_search , hybrid_search
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdminUser
from rest_framework.decorators import permission_classes
from django.db import models , transaction
import json
from api.audit import create_audit_log
from django.http import StreamingHttpResponse
from .services import generate_rag_answer , generate_rag_stream
from .serializers import ( SearchQuerySerializer , ChatAskSerializer , )
@api_view(["POST"])
@permission_classes([IsAdminUser])
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
    result_chunk_ids = [
        result["chunk_id"]
        for result in results
    ]

    allowed_chunk_ids = set(
        DocumentChunk.objects.filter(
            id__in=result_chunk_ids
        ).filter(
            models.Q(document__is_public=True)
            | models.Q(
                document__department_id=request.user.department_id
            )
        ).values_list(
            "id",
            flat=True,
        )
    )

    results = [
        result
        for result in results
        if result["chunk_id"] in allowed_chunk_ids
    ]
    results = [
        result
        for result in results
        if float(result["rerank_score"]) > 0
    ]
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
        create_audit_log(
    request.user,
    "SEARCH",
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
    
    create_audit_log(
    request.user,
    "RAG_QUERY",
)
    
    return Response(
        {
            "query_text": query_text,
            "answer": result["answer"],
            "citations": result["citations"],
        },
        status=status.HTTP_200_OK,
    )
@extend_schema(
    request=ChatAskSerializer,
    responses={
        200: OpenApiResponse(
            description="Streaming chat answer with citations",
        ),
    },
)
@api_view(["POST"])
@throttle_classes([ChatUserRateThrottle])
def chat_ask_view(request):
    serializer = ChatAskSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    question = serializer.validated_data["question"]

    def event_stream():
        try:
            for event in generate_rag_stream(
                question,
                user=request.user,
            ):
                event_type = event["type"]

                if event_type == "token":
                    data = {
                        "content": event["content"],
                    }

                    yield (
                        "event: token\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "citations":
                    yield (
                        "event: citations\n"
                        f"data: {json.dumps(event['citations'], ensure_ascii=False)}\n\n"
                    )

                elif event_type == "error":
                    data = {
                        "error": event["message"],
                    }

                    yield (
                        "event: error\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "done":
                    yield (
                        "event: done\n"
                        "data: {}\n\n"
                    )

        except Exception as exc:
            data = {
                "error": str(exc),
            }

            yield (
                "event: error\n"
                f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            )

    return StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminUser])
def audit_logs_view(request):
    queryset = AuditLog.objects.select_related("user").all()

    user_id = request.query_params.get("user_id")
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")

    if user_id:
        queryset = queryset.filter(user_id=user_id)

    if date_from:
        parsed_date_from = parse_date(date_from)

        if parsed_date_from is None:
            return Response(
                {"error": "Invalid date_from format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = queryset.filter(
            timestamp__date__gte=parsed_date_from
        )

    if date_to:
        parsed_date_to = parse_date(date_to)

        if parsed_date_to is None:
            return Response(
                {"error": "Invalid date_to format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = queryset.filter(
            timestamp__date__lte=parsed_date_to
        )

    serializer = AuditLogSerializer(
        queryset,
        many=True,
    )

    return Response(
        serializer.data,
        status=status.HTTP_200_OK,
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_analytics_view(request):
    # Overall document statistics
    document_stats = Document.objects.aggregate(
        total_documents=Count("id"),
        total_file_size_bytes=Sum("file_size"),
    )

    # Overall search statistics
    total_searches = SearchQuery.objects.count()

    # Aggregate document statistics per department
    department_documents = (
        Document.objects
        .values("department_id")
        .annotate(
            document_count=Count("id"),
            file_size_bytes=Sum("file_size"),
        )
    )

    document_stats_by_department = {
        item["department_id"]: item
        for item in department_documents
    }

    # Aggregate search statistics per user's current department
    department_searches = (
        SearchQuery.objects
        .filter(user__department_id__isnull=False)
        .values("user__department_id")
        .annotate(search_count=Count("id"))
    )

    search_stats_by_department = {
        item["user__department_id"]: item["search_count"]
        for item in department_searches
    }

    departments_data = []

    for department in Department.objects.all().order_by("name"):
        document_data = document_stats_by_department.get(
            department.id,
            {},
        )

        departments_data.append({
            "department_id": department.id,
            "department_name": department.name,
            "document_count": document_data.get("document_count", 0),
            "file_size_bytes": document_data.get("file_size_bytes") or 0,
            "search_count": search_stats_by_department.get(
                department.id,
                0,
            ),
        })

    # Return only the 10 most recent searches
    recent_searches_queryset = (
        SearchQuery.objects
        .select_related("user", "user__department")
        .order_by("-created_at", "-id")[:10]
    )

    recent_searches = [
        {
            "id": search.id,
            "username": search.user.username,
            "department_name": (
                search.user.department.name
                if search.user.department
                else None
            ),
            "query_text": search.query_text,
            "created_at": search.created_at,
        }
        for search in recent_searches_queryset
    ]

    return Response(
        {
            "total_documents": document_stats["total_documents"],
            "total_file_size_bytes": (
                document_stats["total_file_size_bytes"] or 0
            ),
            "total_searches": total_searches,
            "departments": departments_data,
            "recent_searches": recent_searches,
        },
        status=status.HTTP_200_OK,
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    user = request.user

    return Response({
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "department_id": user.department_id,
        "department_name": (
            user.department.name if user.department else None
        ),
    })