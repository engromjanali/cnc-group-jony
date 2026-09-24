from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from storage.models import StoredFile


class UserManager(BaseUserManager):
    """Manager for a User model that authenticates by email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address.')
        # An account made with a password has one; one made without (a Google
        # sign-up) does not, until the user sets it.
        extra_fields.setdefault('password_set', bool(password))
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Project user. Email is the login identifier; the username field is dropped."""

    username = None
    email = models.EmailField('email address', unique=True)
    phone = models.CharField(max_length=32, blank=True)
    # Uploaded to Cloudinary by this backend, like a design's preview image.
    # There is no URL field to set directly - avatars only ever come from a
    # multipart upload on the profile endpoint.
    avatar_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    # The Firebase Auth user behind this account's Google sign-in - the stable
    # link to that identity. Email can change; this cannot. Set the first time
    # the user signs in with Google; blank for an account that has only ever
    # used email + password (which this backend handles itself, not Firebase).
    firebase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    # Whether the account has a password of its own. False for a Google sign-up
    # until the user sets one (POST /auth/set-password).
    password_set = models.BooleanField(default=False)
    # Only ever changed by an admin approving a wallet top-up (see the wallet app).
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email
