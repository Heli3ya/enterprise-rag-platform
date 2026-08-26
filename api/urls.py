from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import create_embeddings , semantic_search_view , search_query_view


urlpatterns = [
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('embeddings/create/', create_embeddings, name='create_embeddings'),
    path('search/', semantic_search_view, name='semantic_search'),
    path("query/search/",search_query_view,name="search_query",
),
]