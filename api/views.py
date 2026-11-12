
import json
import logging
import uuid

import requests
from django.conf import settings
from django.db import models, transaction
from django.db.models import Sum, Count
from django.db import connection as db_connection
from django.db.utils import IntegrityError
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_date

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    throttle_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .throttles import ChatUserRateThrottle, FeedbackUserRateThrottle
from .permissions import IsAdminUser
from .services import (
    MISSING_RERANK_SCORE,
    AIServiceError,
    AIServiceUnavailable,
    generate_embeddings,
    hybrid_search,
    generate_rag_answer,
    generate_rag_stream,
)
from .serializers import (
    AnswerFeedbackSerializer,
    ChatAskSerializer,
    FeedbackCreateSerializer,
    RagQuerySerializer,
    SearchQuerySerializer,
)
from .audit import create_audit_log

from api.models import AnswerFeedback, AuditLog, ChatAnswer
from api.serializers import AuditLogSerializer
from departments.models import Department
from documents.models import (
    Document,
    DocumentChunk,
    Embedding,
    SearchQuery,
    QueryResult,
)


logger = logging.getLogger(__name__)


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


def _department_required_response(request):
    """
    Reject search requests from users without a department.

    Without a department there is no document scope, so the search would
    silently return an empty result set. A clear error is much easier to
    act on.
    """

    if getattr(request.user, "department_id", None) is None:
        return Response(
            {
                "detail": (
                    "Your account is not assigned to a department. "
                    "Ask an administrator to assign one before searching."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    return None


def _ai_service_error_response(exc, fallback_message):
    """
    Translate AI service failures into a clear HTTP response.

    A missing AI service is a temporary condition, so it is reported as
    503 instead of a generic 500.
    """

    if isinstance(exc, AIServiceUnavailable):
        return Response(
            {
                "error": (
                    "The AI service is not available right now. "
                    "Please try again in a moment."
                ),
                "detail": str(exc),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, AIServiceError):
        return Response(
            {"error": str(exc) or fallback_message},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(
        {"error": str(exc) or fallback_message},
        status=status.HTTP_502_BAD_GATEWAY,
    )


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


def _persist_chat_answer(
    *,
    answer_id,
    user,
    conversation_id,
    question,
    answer,
    citations,
    is_complete,
):
    """
    Store a generated answer without ever breaking the chat response.

    Persistence is a side effect of the chat, not part of its contract:
    a database hiccup must not turn a delivered answer into an error, so
    failures are logged and swallowed. `update_or_create` keeps the call
    idempotent if a stream is replayed.

    The row is written *before* the `done` event is sent, so a client that
    posts feedback immediately after `done` always finds its target.
    """

    try:
        ChatAnswer.objects.update_or_create(
            id=answer_id,
            defaults={
                "tenant_id": getattr(user, "tenant_id", None),
                "user": user,
                "conversation_id": conversation_id or "",
                "question": question,
                "answer": answer,
                "citations": citations or [],
                "is_complete": is_complete,
            },
        )
    except Exception:
        logger.exception(
            "Failed to persist chat answer %s",
            answer_id,
        )


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
        # Replace any previous embedding for these chunks, otherwise the
        # vector search would return the same chunk several times.
        Embedding.objects.filter(
            chunk_id__in=[chunk.id for chunk in chunks],
        ).delete()

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

    department_error = _department_required_response(request)
    if department_error:
        return department_error

    try:
        # Database ownership is verified below before any result is returned.
        results = hybrid_search(
            query,
            limit=5,
            user=request.user,
        )
    except Exception as exc:
        return _ai_service_error_response(
            exc,
            "Search service unavailable",
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

    department_error = _department_required_response(request)
    if department_error:
        return department_error

    try:
        results = hybrid_search(
            query_text,
            limit=top_k,
            user=request.user,
        )
    except Exception as exc:
        return _ai_service_error_response(
            exc,
            "Search service unavailable",
        )

    results = _filter_tenant_search_results(results, request)

    # Keep every result the reranker actually scored. Cross-encoder
    # scores are raw logits and are often negative for valid matches, so
    # filtering on "> 0" used to drop every result.
    results = [
        result
        for result in results
        if result.get("rerank_score") != MISSING_RERANK_SCORE
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
    request=RagQuerySerializer,
    responses=OpenApiResponse(
        description="RAG answer with citations and an answer_id",
    ),
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rag_query_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    serializer = RagQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    query_text = serializer.validated_data["query_text"]
    top_k = serializer.validated_data["top_k"]

    department_error = _department_required_response(request)
    if department_error:
        return department_error

    try:
        result = generate_rag_answer(
            query_text,
            limit=top_k,
            user=request.user,
        )
    except Exception as exc:
        return _ai_service_error_response(
            exc,
            "RAG service unavailable",
        )

    create_audit_log(request.user, "RAG_QUERY")

    # Nothing was retrieved, so nothing is stored: there is no answer to
    # rate, and a feedback row pointing at an empty answer would only
    # pollute the training export.
    if result.get("no_documents"):
        return Response(
            {
                "query_text": query_text,
                "answer": result["answer"],
                "citations": [],
                "answer_id": None,
                "no_documents": True,
                "reason": result["reason"],
            },
            status=status.HTTP_200_OK,
        )

    # Persist the answer so the client can rate it through
    # POST /api/chat/feedback/ using the returned `answer_id`.
    answer_id = uuid.uuid4()

    _persist_chat_answer(
        answer_id=answer_id,
        user=request.user,
        conversation_id=serializer.validated_data.get(
            "conversation_id",
            "",
        ),
        question=query_text,
        answer=result["answer"],
        citations=result["citations"],
        is_complete=True,
    )

    return Response(
        {
            "query_text": query_text,
            "answer": result["answer"],
            "citations": result["citations"],
            "answer_id": str(answer_id),
            "no_documents": False,
            "reason": None,
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    request=ChatAskSerializer,
    responses={
        200: OpenApiResponse(
            description=(
                "Server-sent events stream. The first event is `meta` and "
                "carries the `answer_id` needed by "
                "POST /api/chat/feedback/, followed by `token`, "
                "`citations` and `done` events.\n\n"
                "When the department has no searchable document, or "
                "nothing matches the question, a single `no_documents` "
                "event (`reason`: `empty_department` or `no_match`) is "
                "sent instead of `token`/`citations` and the LLM is "
                "never called. No answer row is stored in that case, so "
                "the `answer_id` from `meta` cannot be rated."
            ),
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
    conversation_id = serializer.validated_data["conversation_id"]

    department_error = _department_required_response(request)
    if department_error:
        return department_error

    # Generated up front so the client learns its ID before the first
    # token arrives, while the row is still written only once.
    answer_id = uuid.uuid4()

    def event_stream():
        answer_text = ""
        citations = []
        is_complete = False
        # Set by the cold-start branch: nothing was retrieved, so there
        # is no answer row to write and no answer_id worth rating.
        no_documents = False

        try:
            meta = json.dumps(
                {
                    "answer_id": str(answer_id),
                    "conversation_id": conversation_id,
                },
                ensure_ascii=False,
            )
            yield f"event: meta\ndata: {meta}\n\n"

            for event in generate_rag_stream(
                question,
                user=request.user,
            ):
                event_type = event["type"]

                if event_type == "token":
                    answer_text += event["content"]

                    data = {"content": event["content"]}
                    yield (
                        "event: token\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "citations":
                    citations = event["citations"]

                    yield (
                        "event: citations\n"
                        "data: "
                        f"{json.dumps(citations, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "no_documents":
                    # Cold start: nothing was retrieved, so no LLM call
                    # was made. `reason` lets the UI choose between an
                    # upload prompt and a "rephrase that" hint.
                    no_documents = True

                    data = {
                        "reason": event["reason"],
                        "message": event["message"],
                    }
                    yield (
                        "event: no_documents\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "error":
                    data = {"error": event["message"]}
                    yield (
                        "event: error\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                elif event_type == "done":
                    if no_documents:
                        # An empty answer is not an answer: storing it
                        # would put a blank row into the fine-tuning
                        # export and hand the client a rateable id for
                        # something that was never generated.
                        yield "event: done\ndata: {}\n\n"
                        return

                    # Write before announcing completion: a client that
                    # posts feedback on `done` must never find a missing
                    # answer row.
                    _persist_chat_answer(
                        answer_id=answer_id,
                        user=request.user,
                        conversation_id=conversation_id,
                        question=question,
                        answer=answer_text,
                        citations=citations,
                        is_complete=True,
                    )
                    is_complete = True

                    yield "event: done\ndata: {}\n\n"

        except Exception as exc:
            if isinstance(exc, AIServiceUnavailable):
                message = (
                    "The AI service is not available right now. "
                    "Please try again in a moment."
                )
            else:
                message = str(exc) or "RAG service unavailable"

            data = {"error": message}
            yield (
                "event: error\n"
                f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            )

        finally:
            # Covers both failures and client disconnects: whatever was
            # produced is kept, flagged so it never enters training data.
            if not is_complete and (answer_text or citations):
                _persist_chat_answer(
                    answer_id=answer_id,
                    user=request.user,
                    conversation_id=conversation_id,
                    question=question,
                    answer=answer_text,
                    citations=citations,
                    is_complete=False,
                )

    return StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )


@extend_schema(
    summary="Submit feedback for a chat answer",
    description=(
        "Records whether a generated answer was useful. Each user may "
        "rate a given answer exactly once; the database enforces this, "
        "so a repeated submission returns 409 instead of creating a "
        "second row.\n\n"
        "The `answer_id` is delivered in the `meta` event of "
        "`POST /api/chat/ask/` and in the response of "
        "`POST /api/query/ask/`."
    ),
    request=FeedbackCreateSerializer,
    responses={
        201: AnswerFeedbackSerializer,
        400: OpenApiResponse(description="Invalid payload."),
        401: OpenApiResponse(description="Authentication required."),
        403: OpenApiResponse(description="No active tenant."),
        404: OpenApiResponse(
            description="Answer not found for this user.",
        ),
        409: OpenApiResponse(
            description="Feedback already submitted for this answer.",
        ),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([FeedbackUserRateThrottle])
def chat_feedback_view(request):
    """
    Store one user's verdict on one answer.

    The answer lookup is scoped to the requesting user *and* their
    tenant, so an `answer_id` leaked from another organisation (or from a
    colleague) resolves to 404 rather than exposing that it exists.
    """

    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    serializer = FeedbackCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    answer_id = serializer.validated_data["answer_id"]
    is_positive = serializer.validated_data["is_positive"]
    user_comment = serializer.validated_data["user_comment"]

    answer = ChatAnswer.objects.filter(
        id=answer_id,
        user=request.user,
        tenant_id=request.user.tenant_id,
    ).first()

    if answer is None:
        return Response(
            {"error": "Answer not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Fast, friendly path for the common duplicate. The unique
    # constraint below is what actually guarantees the rule.
    if AnswerFeedback.objects.filter(
        answer=answer,
        user=request.user,
    ).exists():
        return Response(
            {"error": "Feedback already submitted for this answer."},
            status=status.HTTP_409_CONFLICT,
        )

    try:
        with transaction.atomic():
            feedback = AnswerFeedback.objects.create(
                answer=answer,
                user=request.user,
                tenant_id=request.user.tenant_id,
                is_positive=is_positive,
                user_comment=user_comment,
            )
    except IntegrityError:
        # Two concurrent submissions: the loser of the race gets the
        # same answer as a sequential duplicate.
        return Response(
            {"error": "Feedback already submitted for this answer."},
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        AnswerFeedbackSerializer(feedback).data,
        status=status.HTTP_201_CREATED,
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
    ).exclude(is_system=True)

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
            "tenant_id": user.tenant_id,
            "tenant_name": (
                user.tenant.name if user.tenant_id else None
            ),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    """
    Public health endpoint.

    It reports whether the database and the AI inference service are
    reachable, which makes deployment problems easy to diagnose.
    """

    database_status = "unknown"

    try:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()

        database_status = "connected"

    except Exception as exc:
        database_status = f"error: {exc}"

    ai_status = "unknown"
    ai_detail = ""

    try:
        response = requests.get(
            f"{settings.AI_SERVICE_URL}/health",
            timeout=(2, 5),
        )
        response.raise_for_status()

        payload = response.json()
        ai_status = "connected"
        ai_ready = bool(payload.get("ready", True))
        ai_detail = "models are ready" if ai_ready else "models are still loading"

    except Exception as exc:
        ai_status = "unavailable"
        ai_detail = str(exc)

    overall = (
        "ok"
        if database_status == "connected" and ai_status == "connected"
        else "degraded"
    )

    return Response(
        {
            "status": overall,
            "database": database_status,
            "ai_service": {
                "status": ai_status,
                "detail": ai_detail,
            },
        },
        status=status.HTTP_200_OK,
    )
