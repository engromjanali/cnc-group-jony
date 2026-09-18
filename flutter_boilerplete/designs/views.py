from rest_framework import generics, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from .models import Category, Design, SubCategory
from .serializers import (
    CategorySerializer,
    DesignDetailSerializer,
    DesignWriteSerializer,
    SubCategorySerializer,
)


class CategoryListView(generics.ListAPIView):
    """GET /api/v1/category/list"""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


class SubCategoryListView(generics.ListAPIView):
    """GET /api/v1/subcategory/list?category=<id>"""

    serializer_class = SubCategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        queryset = SubCategory.objects.select_related('category').all()
        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        return queryset


class AdminCategoryCreateView(generics.CreateAPIView):
    """POST /api/v1/admin/category/add"""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAdminUser]


class AdminSubCategoryCreateView(generics.CreateAPIView):
    """POST /api/v1/admin/subcategory/add"""

    queryset = SubCategory.objects.all()
    serializer_class = SubCategorySerializer
    permission_classes = [permissions.IsAdminUser]


class DesignPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminDesignListView(generics.ListAPIView):
    """GET /api/v1/admin/design/list?search=&category=&page="""

    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = DesignPagination

    def get_queryset(self):
        queryset = Design.objects.select_related('category', 'sub_category').all()

        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset


class AdminDesignAddView(generics.CreateAPIView):
    """POST /api/v1/admin/design/add"""

    queryset = Design.objects.all()
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminDesignUpdateView(generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/design/update/<id>"""

    queryset = Design.objects.all()
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminDesignDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/design/delete/<id>"""

    queryset = Design.objects.all()
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]


class DesignDetailView(generics.RetrieveAPIView):
    """GET /api/v1/design/details/<id>"""

    queryset = Design.objects.select_related('category', 'sub_category').all()
    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
