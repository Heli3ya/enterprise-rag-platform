from django.urls import path
from .views import DocumentUploadView, DocumentStatusView

urlpatterns = [
    path("", DocumentUploadView.as_view(), name="document-upload"),
    path("<int:pk>/", DocumentStatusView.as_view(), name="document-status"),
]