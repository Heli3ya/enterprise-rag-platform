from django.urls import path
from .views import DepartmentListView


urlpatterns = [
    path('departments/', DepartmentListView.as_view(), name='department-list'),
]