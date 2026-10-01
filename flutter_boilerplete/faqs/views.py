from rest_framework import generics, permissions
from rest_framework.parsers import JSONParser

from .models import Faq
from .serializers import FaqSerializer


class FaqListView(generics.ListAPIView):
    """GET /api/v1/faq/list - the FAQs to show in the app: switched on, ordered
    by `order` (lowest first), then oldest first."""

    queryset = Faq.objects.filter(is_active=True)
    serializer_class = FaqSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


class AdminFaqListView(generics.ListAPIView):
    """GET /api/v1/admin/faq/list - every FAQ, switched-off ones included."""

    queryset = Faq.objects.all()
    serializer_class = FaqSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None


class AdminFaqAddView(generics.CreateAPIView):
    """POST /api/v1/admin/faq/add

    JSON body: `question` and `answer` (required), and optionally `order`
    (default 0) and `is_active` (default true)."""

    queryset = Faq.objects.all()
    serializer_class = FaqSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [JSONParser]


class AdminFaqUpdateView(generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/faq/update/<id> - same fields as add, all
    optional on PATCH."""

    queryset = Faq.objects.all()
    serializer_class = FaqSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [JSONParser]


class AdminFaqDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/faq/delete/<id>"""

    queryset = Faq.objects.all()
    permission_classes = [permissions.IsAdminUser]
