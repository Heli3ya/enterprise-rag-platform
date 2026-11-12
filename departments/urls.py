from django.urls import path
from .views import (
    DepartmentCreateView,
    DepartmentListView,
    DepartmentReadinessView,
)

urlpatterns = [
    path('departments/', DepartmentListView.as_view(), name='department-list'),
    path('departments/create/', DepartmentCreateView.as_view(), name='department-create'),
    path(
        'departments/readiness/',
        DepartmentReadinessView.as_view(),
        name='department-readiness',
    ),
]