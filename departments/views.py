
# Create your views here.
from rest_framework.generics import ListAPIView
from .models import Department
from .serializers import DepartmentSerializer


class DepartmentListView(ListAPIView):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer