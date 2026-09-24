from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import (
    AdminUserSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    LogoutSerializer,
    RegisterSerializer,
    SetPasswordSerializer,
    UserSerializer,
    token_pair,
)


class RegisterView(APIView):
    """POST /api/v1/auth/register - create an account and return a token pair."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {'user': UserSerializer(user).data, 'tokens': token_pair(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """POST /api/v1/auth/login - exchange email + password for a token pair."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        return Response({'user': UserSerializer(user).data, 'tokens': token_pair(user)})


class GoogleLoginView(APIView):
    """POST /api/v1/auth/google - sign in or sign up with Google.

    Body: `{ "id_token": "<Firebase ID token>" }` from Firebase Auth's Google
    provider (the only thing Firebase is used for - email + password accounts
    live in this backend). Answers `{ user, tokens, is_new_user, password_set }`:
    `201` when the sign-in made the account, `200` otherwise. `400`
    (`id_token`) when the token is invalid, expired, for another project, not
    from Google, or has no verified email; `400` too for a disabled account.
    Normal API calls then use the returned access token, never the Firebase
    one."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        created = serializer.validated_data['created']
        return Response(
            {
                'user': UserSerializer(user).data,
                'tokens': token_pair(user),
                'is_new_user': created,
                'password_set': user.password_set,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SetPasswordView(APIView):
    """POST /api/v1/auth/set-password - give the signed-in account a password.

    Needs the backend access token, so nobody can set a password on an account
    that is not theirs. Body: `{ "password", "password_confirmation" }`. Only
    for an account that has none (a Google sign-up): `400` if one is already
    set, if they differ, or if the password fails Django's validators. Once set,
    the account can also sign in with email + password (`/auth/login`). Never
    returns or logs the password."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['password'])
        user.password_set = True
        user.save(update_fields=['password', 'password_set'])
        return Response({'message': 'Password set successfully.', 'password_set': True})


class LogoutView(APIView):
    """POST /api/v1/auth/logout - blacklist the supplied refresh token."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data['refresh']).blacklist()
        except TokenError:
            return Response(
                {'detail': 'Token is invalid or already expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/user/profile - the authenticated user's own record."""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class AdminUserPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminUserListView(generics.ListAPIView):
    """GET /api/v1/admin/users/list?search=&is_active=&page=

    Every account, newest first. `search` matches (case-insensitive) the
    email, first name or last name; `is_active` (`true`/`false`) filters
    enabled/disabled accounts. Both are optional and combine."""

    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = AdminUserPagination

    def get_queryset(self):
        queryset = User.objects.all().order_by('-date_joined')

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.strip().lower() == 'true')

        return queryset


class AdminUserUpdateView(generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/users/update/<id>

    Edits `first_name`, `last_name`, `phone` and/or `is_active`. Setting
    `is_active` to `false` disables the account: sign-in is refused and every
    token already issued for it stops working on the next request. An admin
    cannot disable their own account this way."""

    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]
