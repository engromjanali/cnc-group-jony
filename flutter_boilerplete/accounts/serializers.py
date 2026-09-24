from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from storage.models import StoredFile
from storage.services import delivery_url
from storage.uploads import discard, store_upload
from storage.validators import validate_image_upload

from . import firebase
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user, returned by register/login/profile.

    `avatar` is write-only: a multipart image upload that this backend sends
    to Cloudinary, the same way a design's preview image is handled. Reads
    only ever see `avatar_url`, built on demand from the stored file.
    """

    avatar = serializers.ImageField(write_only=True, required=False)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'phone',
            'avatar', 'avatar_url', 'wallet_balance', 'password_set', 'date_joined', 'updated_at',
        )
        read_only_fields = (
            'id', 'email', 'wallet_balance', 'password_set', 'date_joined', 'updated_at',
        )

    def get_avatar_url(self, obj):
        return delivery_url(obj.avatar_file.storage_key) if obj.avatar_file_id else None

    def validate_avatar(self, avatar):
        return validate_image_upload(avatar)

    def update(self, instance, validated_data):
        avatar = validated_data.pop('avatar', None)
        if avatar is None:
            return super().update(instance, validated_data)

        stored = store_upload(
            instance, StoredFile.Provider.CLOUDINARY, avatar,
            file_name=avatar.name, content_type=avatar.content_type,
        )
        previous = instance.avatar_file if instance.avatar_file_id else None
        try:
            validated_data['avatar_file'] = stored
            instance = super().update(instance, validated_data)
        except Exception:
            discard(stored)
            raise
        if previous is not None:
            discard(previous)
        return instance


class AdminUserSerializer(serializers.ModelSerializer):
    """Used by the admin user list and the admin edit endpoint.

    An admin edits `first_name`, `last_name`, `phone` and `is_active` -
    switching `is_active` off is how an account is disabled, and back on is how
    it is re-enabled. `email` and `wallet_balance` are read-only here too:
    email never changes, and the wallet only moves through a top-up approval or
    the admin credit endpoint, both of which keep their own record of why."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'phone', 'avatar_url',
            'wallet_balance', 'is_active', 'date_joined', 'updated_at',
        )
        read_only_fields = ('id', 'email', 'wallet_balance', 'date_joined', 'updated_at')

    def get_avatar_url(self, obj):
        return delivery_url(obj.avatar_file.storage_key) if obj.avatar_file_id else None

    def validate_is_active(self, value):
        request = self.context.get('request')
        if not value and request is not None and self.instance == request.user:
            raise serializers.ValidationError("You can't disable your own account.")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'password_confirm', 'first_name', 'last_name', 'phone')

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get('request'),
            username=attrs['email'],
            password=attrs['password'],
        )
        if user is None:
            raise serializers.ValidationError('Invalid email or password.')
        if not user.is_active:
            raise serializers.ValidationError('This account has been disabled.')
        attrs['user'] = user
        return attrs


class GoogleLoginSerializer(serializers.Serializer):
    """`POST /auth/google` - sign in (or sign up) with a Google account.

    `id_token` is the Firebase ID token from Firebase Auth's Google provider.
    It is verified first (`accounts.firebase`), then the local user is found or
    made - see `_resolve_user` for exactly how."""

    id_token = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            claims = firebase.verify_firebase_token(attrs['id_token'])
        except firebase.InvalidFirebaseToken as error:
            raise serializers.ValidationError({'id_token': str(error)})

        if firebase.provider_of(claims) != firebase.GOOGLE:
            raise serializers.ValidationError(
                {'id_token': 'This sign-in did not come from Google.'},
            )

        user, created = self._resolve_user(claims)
        attrs['user'] = user
        attrs['created'] = created
        return attrs

    def _resolve_user(self, claims):
        """The local user for a verified Google sign-in, and whether it is new.

        1. **By Firebase UID** - the stable identity, so a changed email never
           makes a second account.
        2. **By email**, when no account carries that UID yet. Google has
           verified the address (`verify_firebase_token` insists), so the
           sign-in proves control of the mailbox and the account - say, one
           made with email + password - is *linked*: it gets the UID and from
           then on is found by step 1. An account already linked to a
           *different* Google user is refused, never re-pointed.
        3. Otherwise a new account, with no password until the user sets one
           (`POST /auth/set-password`).
        """
        uid = claims['sub']
        email = User.objects.normalize_email(claims['email'])

        user = User.objects.filter(firebase_uid=uid).first()
        if user is None:
            user = User.objects.filter(email__iexact=email).first()
            if user is not None:
                if user.firebase_uid and user.firebase_uid != uid:
                    raise serializers.ValidationError(
                        'This email is already linked to a different Google account.',
                    )
                if user.is_active:
                    user.firebase_uid = uid
                    user.save(update_fields=['firebase_uid'])

        if user is not None:
            if not user.is_active:
                raise serializers.ValidationError('This account has been disabled.')
            return user, False

        first, _, last = (claims.get('name') or '').strip().partition(' ')
        user = User(
            email=email, firebase_uid=uid,
            first_name=first[:150], last_name=last.strip()[:150],
        )
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            # Two first sign-ins raced; the other one made the account.
            return User.objects.get(firebase_uid=uid), False
        return user, True


class SetPasswordSerializer(serializers.Serializer):
    """Give an account that has no password (a Google sign-up) one, so it can
    also sign in with email + password through this backend."""

    password = serializers.CharField(write_only=True)
    password_confirmation = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context['request'].user
        if user.password_set:
            raise serializers.ValidationError(
                'This account already has a password. Use "forgot password" to change it.',
            )
        if attrs['password'] != attrs['password_confirmation']:
            raise serializers.ValidationError(
                {'password_confirmation': 'Passwords do not match.'},
            )
        # Also refuses one too close to the email/name, which is why it needs
        # the user.
        validate_password(attrs['password'], user=user)
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


def token_pair(user):
    """Issue an access/refresh pair for `user`."""
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}
