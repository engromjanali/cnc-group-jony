from rest_framework import generics, permissions
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from storage.uploads import discard
from storage.views import StorageErrorsMixin

from .models import Banner
from .serializers import BannerSerializer


class BannerListView(generics.ListAPIView):
    """GET /api/v1/banner/list - the banners to show right now: switched on,
    inside their schedule, ordered by priority (lowest first, unset last), then
    newest."""

    serializer_class = BannerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        # Built per request: `live()` compares against the current time.
        return Banner.objects.live().select_related('image_file', 'category')


class AdminBannerListView(generics.ListAPIView):
    """GET /api/v1/admin/banner/list - every banner, including switched-off,
    scheduled and expired ones. `status` says which."""

    queryset = Banner.objects.select_related('image_file', 'category')
    serializer_class = BannerSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None


class AdminBannerAddView(StorageErrorsMixin, generics.CreateAPIView):
    """POST /api/v1/admin/banner/add

    Multipart fields: title, image (file, required), and optionally cta_label,
    category, is_active, priority, start_at, end_at. At most 10 banners can
    exist; beyond that it returns 409 without uploading anything."""

    queryset = Banner.objects.all()
    serializer_class = BannerSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminBannerUpdateView(StorageErrorsMixin, generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/banner/update/<id>

    Same fields as add, all optional on PATCH. A replaced image is removed from
    storage automatically once the new one is saved."""

    queryset = Banner.objects.select_related('image_file', 'category')
    serializer_class = BannerSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminBannerDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/banner/delete/<id> - also removes the banner's
    image from Cloudinary."""

    queryset = Banner.objects.select_related('image_file')
    permission_classes = [permissions.IsAdminUser]

    def perform_destroy(self, instance):
        image = instance.image_file
        super().perform_destroy(instance)
        if image is not None:
            discard(image)
