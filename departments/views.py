
# Create your views here.
from rest_framework.generics import ListAPIView , CreateAPIView
from .models import Department
from .serializers import DepartmentSerializer  
from api.permissions import IsAdminUser

class DepartmentListView(ListAPIView):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    
class DepartmentCreateView(CreateAPIView):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAdminUser]