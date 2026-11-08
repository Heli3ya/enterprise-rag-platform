from django.urls import path

from .views import (
    DocumentUploadView,
    DocumentStatusView,
    DocumentDeleteView,
    DocumentFileView,
    DocumentPreviewView,
    ChunkDetailView,
)

urlpatterns = [
    path("", DocumentUploadView.as_view(), name="document-upload"),
    # Must be registered before the "<int:pk>/" routes so a chunk id
    # is never mistaken for a document id.
    path("chunks/<int:pk>/", ChunkDetailView.as_view(), name="chunk-detail"),
    path("<int:pk>/", DocumentStatusView.as_view(), name="document-status"),
    path("<int:pk>/file/", DocumentFileView.as_view(), name="document-file"),
    path(
        "<int:pk>/preview/",
        DocumentPreviewView.as_view(),
        name="document-preview",
    ),
    path("<int:pk>/delete/", DocumentDeleteView.as_view(), name="document-delete"),
]
