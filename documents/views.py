import magic
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Document
from .serializers import DocumentSerializer
from drf_spectacular.utils import extend_schema
from .serializers import DocumentStatusSerializer
from rest_framework.exceptions import PermissionDenied

@extend_schema(
    request=DocumentSerializer,
    responses=DocumentSerializer
)

class DocumentUploadView(generics.CreateAPIView):

    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
     file = self.request.FILES.get("file_path")

     file_type = magic.from_buffer(
        file.read(2048),
        mime=True
    )

     file.seek(0)

     serializer.save(
        uploaded_by=self.request.user,
        status="Pending",
        file_type=file_type
    )


    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        self.perform_create(serializer)

        return Response(
            {
                "document_id": serializer.instance.id,
                "status": serializer.instance.status
            },
            status=status.HTTP_201_CREATED
        )
    

class DocumentStatusView(generics.RetrieveAPIView):
    serializer_class = DocumentStatusSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        document = Document.objects.get(
            id=self.kwargs["pk"]
        )

        if document.department != self.request.user.department:
            raise PermissionDenied(
                "You do not have permission to access this document."
            )

        return document
    
class DocumentDeleteView(generics.DestroyAPIView):
    queryset = Document.objects.all()
    permission_classes = [IsAuthenticated]

    def get_object(self):
        document = super().get_object()

        if (
            document.uploaded_by != self.request.user
            and self.request.user.role != "Admin"
        ):
            raise PermissionDenied(
                "You do not have permission to delete this document."
            )

        return document

    def perform_destroy(self, instance):
        if instance.file_path:
            instance.file_path.delete(save=False)

        instance.delete()