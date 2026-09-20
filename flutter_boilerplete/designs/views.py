from django.db.models import Count, Prefetch, ProtectedError
from django.http import Http404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
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
    HomeCategorySerializer,
    SubCategorySerializer,
    legacy_design_file_url,
)

# How many of a category's newest designs the home screen gets, and the most it
# may ask for.
HOME_DESIGNS_PER_CATEGORY = 10
HOME_MAX_DESIGNS_PER_CATEGORY = 50

# How many categories one page of the home screen holds, and the most a client
# may ask for at once.
HOME_CATEGORIES_PER_PAGE = 10
HOME_MAX_CATEGORIES_PER_PAGE = 50


class CategoryListView(generics.ListAPIView):
    """GET /api/v1/category/list - ordered by priority (lowest first, unset
    last), then name. `design_count` / `can_delete` say whether the category
    still has designs."""

    # Ordered explicitly: Django ignores Meta.ordering on a query that
    # aggregates (the Count below turns it into a GROUP BY).
    queryset = (
        Category.objects.select_related('image_file')
        .annotate(design_count=Count('designs'))
        .order_by(*Category._meta.ordering)
    )
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


class HomeCategoryPagination(PageNumberPagination):
    page_size = HOME_CATEGORIES_PER_PAGE
    page_size_query_param = 'page_size'
    max_page_size = HOME_MAX_CATEGORIES_PER_PAGE


class HomeCategoriesView(generics.ListAPIView):
    """GET /api/v1/home/categories-designs?page=1&page_size=10&per_category=10

    Everything the home screen needs, a page of categories at a time: the
    categories that have designs, in the same order as the category list, each
    with its total `design_count` and its newest designs (newest first, at most
    `per_category` of them, 10 unless asked otherwise). A category with no
    designs is left out - the home screen has nothing to show for it - and it is
    left out before the page is cut, so no page is ever short or empty because
    of one. Paginated like the design list: `count`, `next`, `previous`,
    `results`."""

    serializer_class = HomeCategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = HomeCategoryPagination

    def _per_category(self):
        raw = self.request.query_params.get('per_category')
        if not raw:
            return HOME_DESIGNS_PER_CATEGORY
        if not raw.isdecimal() or not 1 <= int(raw) <= HOME_MAX_DESIGNS_PER_CATEGORY:
            raise ValidationError({
                'per_category': f'Must be a number from 1 to {HOME_MAX_DESIGNS_PER_CATEGORY}.',
            })
        return int(raw)

    def get_queryset(self):
        # Sliced per category: Django fetches every category's newest few in a
        # single extra query rather than one per category - and only for the
        # categories on the requested page, as the prefetch runs after the page
        # is cut.
        newest = Design.objects.select_related(
            'category', 'sub_category', 'image_file', 'design_stored_file',
        ).order_by('-created_at', '-id')[:self._per_category()]

        # Ordered explicitly: Django ignores Meta.ordering on a query that
        # aggregates (the Count below turns it into a GROUP BY).
        return (
            Category.objects.select_related('image_file')
            .annotate(design_count=Count('designs'))
            .filter(design_count__gt=0)
            .prefetch_related(Prefetch('designs', queryset=newest, to_attr='latest_designs'))
            .order_by(*Category._meta.ordering)
        )


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


class AdminCategoryCreateView(StorageErrorsMixin, generics.CreateAPIView):
    """POST /api/v1/admin/category/add

    Multipart fields: label, image (file, required), priority (optional)."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminCategoryUpdateView(StorageErrorsMixin, generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/category/update/<id>

    Editing is always allowed, including for a category that has designs."""

    queryset = Category.objects.select_related('image_file')
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminCategoryDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/category/delete/<id>

    A category that still has designs cannot be deleted (409); an empty one is
    deleted along with its sub categories and its image."""

    queryset = Category.objects.select_related('image_file')
    permission_classes = [permissions.IsAdminUser]

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        blocked = Response(
            {
                'detail': (
                    f'"{category.label}" still has designs, so it cannot be deleted. '
                    'Move or delete its designs first - you can still edit it.'
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )
        if category.designs.exists():
            return blocked

        image = category.image_file
        try:
            category.delete()
        except ProtectedError:
            # A design was added between the check above and the delete.
            return blocked
        if image is not None:
            discard(image)
        return Response(status=status.HTTP_204_NO_CONTENT)


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


class DesignListView(generics.ListAPIView):
    """GET /api/v1/category-design/list?category=<id>&page=&page_size=

    The published designs for any signed-in user - the same shape as the design
    details, so it never carries a link to the private cutting file (that is
    fetched per design, just before downloading). Newest first; without
    `category` it lists every design. An unknown category is an empty page, not
    an error."""

    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DesignPagination

    def get_queryset(self):
        queryset = Design.objects.select_related(
            'category', 'sub_category', 'image_file', 'design_stored_file',
        )

        category_id = self.request.query_params.get('category')
        if category_id:
            if not category_id.isdecimal():
                raise ValidationError({'category': 'Must be a category id (a number).'})
            queryset = queryset.filter(category_id=category_id)

        # `id` breaks ties, so designs created in the same instant cannot swap
        # places between pages.
        return queryset.order_by('-created_at', '-id')


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
