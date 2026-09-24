from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from . import password_reset
from .models import PasswordResetCode, User
from .serializers import (
    AdminUserSerializer,
    ForgotPasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    LogoutSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
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


FORGOT_PASSWORD_MESSAGE = 'If an account exists for that email, we have sent it a 6-digit code.'


class ForgotPasswordView(APIView):
    """POST /api/v1/auth/forgot-password - email a 6-digit reset code.

    Body: `{ "email" }`. **Always `200` with the same message**, whether or not
    an account exists, so it can't be used to find out who has one. Only an
    existing, active account is emailed - and a Google sign-up that never set a
    password counts. A code is not sent again within 60 seconds, or more than 5
    times an hour, for the same account (still `200`). Send failures are logged,
    not shown."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = 'password-reset'

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(
            email__iexact=serializer.validated_data['email'], is_active=True,
        ).first()
        if user is not None:
            code = password_reset.issue_code(user)
            if code is not None:
                password_reset.send_code_email(user, code)
        return Response({'message': FORGOT_PASSWORD_MESSAGE})


class ResetPasswordView(APIView):
    """POST /api/v1/auth/reset-password - set a new password with the emailed code.

    Body: `{ "email", "code", "password", "password_confirmation" }`. `400` with
    key `code` for any way the code is unusable (one message for all of them),
    `password_confirmation` when the two differ, `password` when it fails the
    password rules - in which case the code is *not* used up. On success the
    password is set, `password_set` becomes true (so a Google sign-up can now
    also sign in with email + password), the code is spent, and every session
    the account had is signed out (its refresh tokens are blacklisted)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = 'password-reset'

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        with transaction.atomic():
            # Locked, so two requests with the same code can't both win.
            code = PasswordResetCode.objects.select_for_update().get(
                pk=serializer.validated_data['code_id'],
            )
            if code.used_at is not None:
                return Response(
                    {'code': ResetPasswordSerializer.INVALID_CODE},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            code.used_at = timezone.now()
            code.save(update_fields=['used_at'])

            user.set_password(serializer.validated_data['password'])
            user.password_set = True
            user.save(update_fields=['password', 'password_set'])

            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)

        return Response({'message': 'Password reset. You can now sign in.'})


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
