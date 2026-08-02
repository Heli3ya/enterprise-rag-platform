from django.urls import path
from .views import DocumentUploadView


urlpatterns = [
    path(
        "",
        DocumentUploadView.as_view(),
        name="document-upload"
    ),
]