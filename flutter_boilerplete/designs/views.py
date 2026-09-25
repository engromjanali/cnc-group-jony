from django.db.models import Count, ProtectedError, Q
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

from . import purchases
from .models import Category, Design, SubCategory
from .serializers import (
    CategorySerializer,
    DesignDetailSerializer,
    DesignWriteSerializer,
    SubCategorySerializer,
    legacy_design_file_url,
)


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
        queryset = Design.objects.select_related(
            'category', 'category__image_file', 'sub_category', 'image_file', 'design_stored_file',
        ).all()

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
    """GET /api/v1/designs/list?category=&sub_category=&design_type=&is_paid=&search=&page=&page_size=

    The published designs for any signed-in user - the same shape as the design
    details, so it never carries a link to the private cutting file (that is
    fetched per design, just before downloading). Newest first.

    Every filter is optional and they combine (AND):
    - `category`, `sub_category`: ids. An unknown id is an empty page.
    - `design_type`: `2d` or `3d`.
    - `is_paid`: `true` = paid only, `false` = free only.
    - `search`: case-insensitive "contains" on the title, description,
      category label and sub category label. Blank is ignored.

    A malformed value (non-numeric id, other design type, is_paid that is not
    true/false) is a 400 naming the parameter, never silently ignored."""

    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DesignPagination

    def get_queryset(self):
        queryset = Design.objects.select_related(
            'category', 'category__image_file', 'sub_category', 'image_file', 'design_stored_file',
        )

        category_id = self.request.query_params.get('category')
        if category_id:
            if not category_id.isdecimal():
                raise ValidationError({'category': 'Must be a category id (a number).'})
            queryset = queryset.filter(category_id=category_id)

        params = self.request.query_params

        sub_category_id = params.get('sub_category')
        if sub_category_id:
            if not sub_category_id.isdecimal():
                raise ValidationError({'sub_category': 'Must be a sub category id (a number).'})
            queryset = queryset.filter(sub_category_id=sub_category_id)

        design_type = params.get('design_type')
        if design_type:
            if design_type not in Design.DesignType.values:
                raise ValidationError({'design_type': 'Must be "2d" or "3d".'})
            queryset = queryset.filter(design_type=design_type)

        is_paid = params.get('is_paid')
        if is_paid:
            wanted = is_paid.strip().lower()
            if wanted not in ('true', 'false'):
                raise ValidationError({'is_paid': 'Must be "true" or "false".'})
            queryset = queryset.filter(is_paid=wanted == 'true')

        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(category__label__icontains=search)
                | Q(sub_category__label__icontains=search)
            )

        # `id` breaks ties, so designs created in the same instant cannot swap
        # places between pages.
        return queryset.order_by('-created_at', '-id')


class DesignDetailView(generics.RetrieveAPIView):
    """GET /api/v1/design/details/<id>"""

    queryset = Design.objects.select_related(
        'category', 'category__image_file', 'sub_category', 'image_file', 'design_stored_file',
    ).all()
    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]


def _download_payload(design, request):
    """The signed link to a design's cutting file, or a 404 when it has none."""
    stored = design.design_stored_file

    if stored is not None and stored.status == StoredFile.Status.READY:
        download_name = design.design_file_name or stored.original_name
        url = get_storage_service(stored.provider).url_for(
            stored.storage_key, download_name=download_name,
        )
        return {
            'downloadUrl': url,
            'fileName': download_name,
            'expiresIn': storage_config.DOWNLOAD_URL_TTL_SECONDS,
        }

    legacy_url = legacy_design_file_url(design, request)
    if legacy_url is None:
        raise Http404('This design has no downloadable file.')
    return {
        'downloadUrl': legacy_url,
        'fileName': design.design_file_name,
        'expiresIn': None,
    }


def _payment_required(price, balance):
    return Response(
        {
            'detail': 'Not enough balance in your wallet. Add money and try again.',
            'required': str(price),
            'walletBalance': str(balance),
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


class DesignDownloadUrlView(StorageView):
    """GET /api/v1/design/<id>/download-url

    A free design, or a paid one this user already bought, may be downloaded by
    any logged-in user. A paid design they have **not** bought answers `402`:
    buy it first with `POST /design/<id>/download`, which is the call that takes
    the money. Every call signs a new short-lived URL; clients must not keep it."""

    def get(self, request, pk):
        design = get_object_or_404(
            Design.objects.select_related('design_stored_file'), pk=pk,
        )
        if not purchases.is_owned(request.user, design):
            return _payment_required(purchases.price_of(design), request.user.wallet_balance)
        return Response(_download_payload(design, request))


class DesignDownloadView(StorageView):
    """POST /api/v1/design/<id>/download - download a design, paying for it.

    Call this when the user taps download. A **free** design is not charged. A
    **paid** one takes its price from the wallet - **once**: downloading it again
    later, from any device, is free, and a retry or double tap can never charge
    twice. If the wallet holds less than the price it answers `402` with
    `required` and `walletBalance`, and nothing is taken.

    A design with no downloadable file is a `404` *before* anything is charged.

    `200` with the signed link (same `downloadUrl` / `fileName` / `expiresIn` as
    `GET /design/<id>/download-url`) plus `designId`, `charged` (what was taken
    now), `alreadyPurchased` and `walletBalance` (after the charge)."""

    def post(self, request, pk):
        design = get_object_or_404(
            Design.objects.select_related('design_stored_file'), pk=pk,
        )
        # Nothing is charged for a file that cannot be downloaded.
        payload = _download_payload(design, request)

        try:
            charged, already_purchased = purchases.charge_for_design(request.user, design)
        except purchases.InsufficientBalance as error:
            return _payment_required(error.required, error.balance)

        request.user.refresh_from_db(fields=['wallet_balance'])
        return Response({
            'designId': design.pk,
            'charged': str(charged),
            'alreadyPurchased': already_purchased,
            'walletBalance': str(request.user.wallet_balance),
            **payload,
        })
