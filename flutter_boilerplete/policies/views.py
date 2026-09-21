from django.db import transaction
from rest_framework import permissions
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PrivacyPolicy
from .serializers import PrivacyPolicySerializer


# What a client gets before any policy has been written: the same three fields,
# so it never has to handle a different shape - it tells "not written yet" by
# the empty content.
NOT_WRITTEN_YET = {'title': '', 'content': '', 'updated_at': None}


class PrivacyPolicyView(APIView):
    """GET /api/v1/privacy-policy - the policy any signed-in user can read.

    Until an admin has written one it is still a 200, with blank `title` and
    `content` and a null `updated_at`."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        policy = PrivacyPolicy.current()
        if policy is None:
            return Response(NOT_WRITTEN_YET)
        return Response(PrivacyPolicySerializer(policy).data)


class AdminPrivacyPolicyView(APIView):
    """PUT /api/v1/admin/privacy-policy - writes the policy.

    JSON body `{"title": ..., "content": ...}`, both required. It creates the
    policy the first time and replaces it after that, and answers with what
    was saved."""

    permission_classes = [permissions.IsAdminUser]
    parser_classes = [JSONParser]

    def put(self, request):
        serializer = PrivacyPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            policy, _ = PrivacyPolicy.objects.update_or_create(
                pk=PrivacyPolicy.SINGLETON_PK,
                defaults={
                    **serializer.validated_data,
                    'updated_by': request.user,
                },
            )
        return Response(PrivacyPolicySerializer(policy).data)
