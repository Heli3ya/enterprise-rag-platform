
import json

from django.db import models, transaction
from django.db.models import Sum, Count
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_date

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    throttle_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .throttles import ChatUserRateThrottle
from .permissions import IsAdminUser
from .services import (
    generate_embeddings,
    hybrid_search,
    generate_rag_answer,
    generate_rag_stream,
)
from .serializers import SearchQuerySerializer, ChatAskSerializer
from .audit import create_audit_log

from api.models import AuditLog
from api.serializers import AuditLogSerializer
from departments.models import Department
from documents.models import (
    Document,
    DocumentChunk,
    Embedding,
    SearchQuery,
    QueryResult,
)


def _get_tenant_id(request):
    """Return the authenticated user's tenant ID."""
    return getattr(request.user, "tenant_id", None)


def _tenant_required_response(request):
    """Reject requests from users without a tenant."""
    tenant_id = _get_tenant_id(request)

    if tenant_id is None:
        return Response(
            {
                "detail": (
                    "Your account is not assigned to an organization."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = getattr(request.user, "tenant", None)

    if tenant is None or not tenant.is_active:
        return Response(
            {"detail": "Your organization is inactive or unavailable."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return None


def _filter_tenant_search_results(results, request):
    """
    Return only search results whose chunks belong to the user's tenant.

    Never trust the search service's result objects alone for access control.
    Verify chunk ownership against the database before returning results.
    """
    tenant_id = _get_tenant_id(request)

    if tenant_id is None:
        return []

    chunk_ids = [
        result.get("chunk_id")
        for result in results
        if isinstance(result, dict) and result.get("chunk_id") is not None
    ]

    if not chunk_ids:
        return []

    allowed_chunk_ids = set(
        DocumentChunk.objects.filter(
            id__in=chunk_ids,
            document__tenant_id=tenant_id,
            document__department__tenant_id=tenant_id,
        )
        .filter(
            models.Q(document__is_public=True)
            | models.Q(
                document__department_id=request.user.department_id
            )
        )
        .values_list("id", flat=True)
    )

    return [
        result
        for result in results
        if (
            isinstance(result, dict)
            and result.get("chunk_id") in allowed_chunk_ids
        )
    ]


def _get_result_document(result):
    """Support search results containing either a chunk or a direct object."""
    item = result["result"]

    if hasattr(item, "chunk"):
        return item.chunk

    return item


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminUser])
def create_embeddings(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    chunk_ids = request.data.get("chunk_ids", [])

    if not isinstance(chunk_ids, list) or not chunk_ids:
        return Response(
            {"error": "chunk_ids is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    tenant_id = _get_tenant_id(request)

    chunks = (
        DocumentChunk.objects.filter(
            id__in=chunk_ids,
            document__tenant_id=tenant_id,
            document__department__tenant_id=tenant_id,
        )
        .select_related("document", "document__department")
        .distinct()
    )

    if not chunks.exists():
        return Response(
            {"error": "No valid document chunks found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    texts = [chunk.content for chunk in chunks]

    try:
        embeddings, dimension = generate_embeddings(texts)
    except Exception:
        return Response(
            {"error": "Failed to generate embeddings."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    created_embeddings = []

    with transaction.atomic():
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def semantic_search_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    query = request.data.get("query", "")

    if not isinstance(query, str):
        return Response(
            {"error": "query is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    query = query.strip()

    if not query:
        return Response(
            {"error": "query is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Database ownership is verified below before any result is returned.
        results = hybrid_search(query, limit=5)
    except Exception as exc:
        return Response(
            {"error": str(exc) or "Search service unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    results = _filter_tenant_search_results(results, request)

    response_results = []

    for result in results:
        item = _get_result_document(result)

        response_results.append(
            {
                "document_id": item.document_id,
                "document_title": item.document.title,
                "chunk_id": result["chunk_id"],
                "chunk_index": item.chunk_index,
                "score": round(float(result["score"]), 6),
                "content": result["content"],
            }
        )

    return Response(
        {
            "query": query,
            "results": response_results,
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    request=SearchQuerySerializer,
    responses=OpenApiResponse(description="Search results"),
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def search_query_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    serializer = SearchQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    query_text = serializer.validated_data["query_text"]
    top_k = serializer.validated_data["top_k"]

    try:
        results = hybrid_search(
            query_text,
            limit=top_k,
            user=request.user,
        )
    except Exception as exc:
        return Response(
            {"error": str(exc) or "Search service unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    results = _filter_tenant_search_results(results, request)

    results = [
        result
        for result in results
        if float(result.get("rerank_score", 0)) > 0
    ]

    with transaction.atomic():
        search_query = SearchQuery.objects.create(
            user=request.user,
            tenant_id=request.user.tenant_id,
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

        create_audit_log(request.user, "SEARCH")

    response_results = []

    for result in results:
        item = _get_result_document(result)

        response_results.append(
            {
                "chunk_id": result["chunk_id"],
                "document_id": item.document_id,
                "document_title": item.document.title,
                "score": round(float(result["rerank_score"]), 6),
                "content": result["content"],
            }
        )

    return Response(
        {
            "query_text": query_text,
            "results": response_results,
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
@permission_classes([IsAuthenticated])
def rag_query_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

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
            {"error": str(exc) or "RAG service unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    create_audit_log(request.user, "RAG_QUERY")

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
@permission_classes([IsAuthenticated])
@throttle_classes([ChatUserRateThrottle])
def chat_ask_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

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
                    data = {"content": event["content"]}
                    yield (
                        "event: token\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "citations":
                    yield (
                        "event: citations\n"
                        "data: "
                        f"{json.dumps(event['citations'], ensure_ascii=False)}\n\n"
                    )

                elif event_type == "error":
                    data = {"error": event["message"]}
                    yield (
                        "event: error\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "done":
                    yield "event: done\ndata: {}\n\n"

        except Exception as exc:
            data = {
                "error": str(exc) or "RAG service unavailable"
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
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    tenant_id = _get_tenant_id(request)

    queryset = AuditLog.objects.filter(
        tenant_id=tenant_id,
        user__tenant_id=tenant_id,
    ).select_related("user")

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
            timestamp__date__gte=parsed_date_from,
        )

    if date_to:
        parsed_date_to = parse_date(date_to)

        if parsed_date_to is None:
            return Response(
                {"error": "Invalid date_to format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = queryset.filter(
            timestamp__date__lte=parsed_date_to,
        )

    serializer = AuditLogSerializer(queryset, many=True)

    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_analytics_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    tenant_id = _get_tenant_id(request)

    tenant_documents = Document.objects.filter(
        tenant_id=tenant_id,
        department__tenant_id=tenant_id,
    )

    document_stats = tenant_documents.aggregate(
        total_documents=Count("id"),
        total_file_size_bytes=Sum("file_size"),
    )

    tenant_searches = SearchQuery.objects.filter(
        tenant_id=tenant_id,
        user__tenant_id=tenant_id,
    )

    total_searches = tenant_searches.count()

    department_documents = (
        tenant_documents
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

    department_searches = (
        tenant_searches
        .filter(
            user__department_id__isnull=False,
            user__department__tenant_id=tenant_id,
        )
        .values("user__department_id")
        .annotate(search_count=Count("id"))
    )

    search_stats_by_department = {
        item["user__department_id"]: item["search_count"]
        for item in department_searches
    }

    departments_data = []

    for department in Department.objects.filter(
        tenant_id=tenant_id,
    ).order_by("name"):
        document_data = document_stats_by_department.get(
            department.id,
            {},
        )

        departments_data.append(
            {
                "department_id": department.id,
                "department_name": department.name,
                "document_count": document_data.get(
                    "document_count",
                    0,
                ),
                "file_size_bytes": (
                    document_data.get("file_size_bytes") or 0
                ),
                "search_count": search_stats_by_department.get(
                    department.id,
                    0,
                ),
            }
        )

    recent_searches_queryset = (
        tenant_searches
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

    return Response(
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "department_id": user.department_id,
            "department_name": (
                user.department.name if user.department else None
            ),
        },
        status=status.HTTP_200_OK,
    )
