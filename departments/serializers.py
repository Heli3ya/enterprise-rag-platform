from rest_framework import serializers
from .models import Department


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = [
            'id',
            'name',
            'description',
            'created_at',
        ]


class DepartmentReadinessSerializer(serializers.Serializer):
    """
    Everything the dashboard needs to decide between "start here" and
    "you already have a knowledge base".

    `document_count` counts *user* documents only. The automatically
    generated onboarding guide is excluded, otherwise a brand-new
    department would look populated and the empty state would never be
    shown.
    """

    department_id = serializers.IntegerField()
    department_name = serializers.CharField()
    document_count = serializers.IntegerField()
    has_searchable_content = serializers.BooleanField()
    is_empty = serializers.BooleanField()
    onboarding_document_id = serializers.IntegerField(
        allow_null=True,
    )
