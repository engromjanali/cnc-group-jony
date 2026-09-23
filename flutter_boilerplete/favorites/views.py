from rest_framework import generics, permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from designs.models import Design
from designs.serializers import DesignDetailSerializer

from .models import Favorite


class FavoriteListView(generics.ListAPIView):
    """GET /api/v1/favorites/list - the signed-in user's saved designs, most
    recently saved first, in the same shape as the design details."""

    serializer_class = DesignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        favorites = Favorite.objects.filter(user=self.request.user).select_related(
            'design__category', 'design__sub_category',
            'design__image_file', 'design__design_stored_file',
        )
        return [favorite.design for favorite in favorites]


class FavoriteAddView(APIView):
    """POST /api/v1/favorites/add/<design_id> - save a design. Saving one that
    is already saved is not an error."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, design_id):
        design = get_object_or_404(Design, pk=design_id)
        _, created = Favorite.objects.get_or_create(user=request.user, design=design)
        return Response(
            {'design_id': design.pk, 'is_favorite': True},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class FavoriteRemoveView(APIView):
    """DELETE /api/v1/favorites/remove/<design_id> - un-save a design. Removing
    one that is not saved is not an error."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, design_id):
        Favorite.objects.filter(user=request.user, design_id=design_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
