from django.urls import path
from .views import DepartmentListView, DepartmentCreateView

urlpatterns = [
    path('departments/', DepartmentListView.as_view(), name='department-list'),
    path('departments/create/', DepartmentCreateView.as_view(), name='department-create'),
]