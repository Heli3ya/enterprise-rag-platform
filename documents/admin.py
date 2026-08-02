from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'file_type',
        'status',
        'uploaded_by',
        'department',
        'created_at',
    )

    search_fields = ('title',)
    list_filter = ('status', 'file_type')