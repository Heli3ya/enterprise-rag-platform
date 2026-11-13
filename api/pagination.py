from rest_framework.pagination import PageNumberPagination


class AdminListPagination(PageNumberPagination):
    """
    Bounded page size for admin tables.

    `max_page_size` is the important part: without it `?page_size=100000`
    is a free denial-of-service on a table that joins three models per
    row. Twenty is what fits on a laptop screen; a hundred is the most
    one request may ask for.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
