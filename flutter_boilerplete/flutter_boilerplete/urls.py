"""URL configuration for the flutter_boilerplete project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('core.urls')),
    path('api/v1/', include('accounts.urls')),
    path('api/v1/', include('banners.urls')),
    path('api/v1/', include('policies.urls')),
    path('api/v1/', include('app_settings.urls')),
    path('api/v1/', include('designs.urls')),
    path('api/v1/', include('storage.urls')),
    path('api/v1/', include('wallet.urls')),
    path('api/v1/', include('favorites.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
