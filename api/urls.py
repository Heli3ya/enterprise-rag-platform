from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .views import (
    create_embeddings,
    semantic_search_view,
    search_query_view,
    rag_query_view,
    chat_ask_view,
    audit_logs_view,
    admin_analytics_view,
    current_user_view,
)

urlpatterns = [
    path("auth/login/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/me/", current_user_view, name="current_user"),
    path("embeddings/create/", create_embeddings, name="create_embeddings"),
    path("search/", semantic_search_view, name="semantic_search"),
    path("query/search/", search_query_view, name="search_query"),
    path("query/ask/", rag_query_view, name="rag_query"),
    path("chat/ask/", chat_ask_view, name="chat_ask"),
    path("audit-logs/", audit_logs_view, name="audit_logs"),
    path("admin/analytics/", admin_analytics_view, name="admin_analytics"),
]