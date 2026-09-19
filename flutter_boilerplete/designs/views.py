from django.http import Http404
from rest_framework import generics, permissions
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from storage import config as storage_config
from storage.models import StoredFile
from storage.services import get_storage_service
from storage.uploads import discard
from storage.views import StorageErrorsMixin, StorageView

from .models import Category, Design, SubCategory
from .serializers import (
    CategorySerializer,
    DesignDetailSerializer,
    DesignWriteSerializer,
    SubCategorySerializer,
    legacy_design_file_url,
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
        queryset = Design.objects.select_related('category', 'sub_category', 'image_file', 'design_stored_file').all()

        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset


class AdminDesignAddView(StorageErrorsMixin, generics.CreateAPIView):
    """POST /api/v1/admin/design/add - the only call needed to add a design.

    Multipart fields: category, title, image (file), design_file (file), and
    optionally sub_category_label and description. The backend uploads both
    files itself and undoes everything if any step fails."""

    queryset = Design.objects.all()
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminDesignUpdateView(StorageErrorsMixin, generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/design/update/<id>

    Same fields as add, all optional on PATCH. A replaced file is removed from
    storage automatically once the new one is saved."""

    queryset = Design.objects.all()
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminDesignDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/design/delete/<id> - also removes the design's
    files from Cloudinary and R2."""

    queryset = Design.objects.select_related('image_file', 'design_stored_file')
    serializer_class = DesignWriteSerializer
    permission_classes = [permissions.IsAdminUser]

    def perform_destroy(self, instance):
        stored_files = [
            f for f in (instance.image_file, instance.design_stored_file) if f is not None
        ]
        super().perform_destroy(instance)
        for stored_file in stored_files:
            discard(stored_file)


class DesignDetailView(generics.RetrieveAPIView):
    """GET /api/v1/design/details/<id>"""

    queryset = Design.objects.select_related('category', 'sub_category', 'image_file', 'design_stored_file').all()
    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]


class DesignDownloadUrlView(StorageView):
    """GET /api/v1/design/<id>/download-url

    Any logged-in user may download a published design, so there is no owner
    check. Every call signs a new short-lived URL; clients must not keep it."""

    def get(self, request, pk):
        design = get_object_or_404(
            Design.objects.select_related('design_stored_file'), pk=pk,
        )
        stored = design.design_stored_file

        if stored is not None and stored.status == StoredFile.Status.READY:
            download_name = design.design_file_name or stored.original_name
            url = get_storage_service(stored.provider).url_for(
                stored.storage_key, download_name=download_name,
            )
            return Response({
                'downloadUrl': url,
                'fileName': download_name,
                'expiresIn': storage_config.DOWNLOAD_URL_TTL_SECONDS,
            })

        legacy_url = legacy_design_file_url(design, request)
        if legacy_url is None:
            raise Http404('This design has no downloadable file.')
        return Response({
            'downloadUrl': legacy_url,
            'fileName': design.design_file_name,
            'expiresIn': None,
        })
