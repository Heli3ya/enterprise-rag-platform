from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django_prometheus.exports import ExportToDjangoView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api.security import internal_only


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("api/", include("departments.urls")),
    # Operational endpoints: internal network or staff only.
    path(
        "api/schema/",
        internal_only(SpectacularAPIView.as_view()),
        name="schema",
    ),
    path(
        "api/docs/",
        internal_only(
            SpectacularSwaggerView.as_view(url_name="schema"),
        ),
        name="swagger-ui",
    ),
    path("api/documents/", include("documents.urls")),
    path(
        "metrics/",
        internal_only(ExportToDjangoView),
        name="prometheus-metrics",
    ),
]

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT,
)