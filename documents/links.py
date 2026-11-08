"""
URL helpers for links the frontend has to build itself.

`reverse()` returns the full path including the mount prefix
(`/api/documents/30/file/`). The frontend prepends its API base URL,
which already ends in `/api`, so the prefix is stripped here to avoid
requests to `/api/api/documents/...`.
"""

from django.urls import reverse


API_PREFIX = "/api/"


def api_relative_url(name, **kwargs):
    path = reverse(name, kwargs=kwargs)

    if path.startswith(API_PREFIX):
        return path[len(API_PREFIX) - 1:]

    return path


def document_file_url(document_id):
    return api_relative_url("document-file", pk=document_id)


def document_preview_url(document_id):
    return api_relative_url("document-preview", pk=document_id)
