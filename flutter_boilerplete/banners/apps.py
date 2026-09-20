from django.apps import AppConfig


class BannersConfig(AppConfig):
    name = 'banners'

    def ready(self):
        from storage.registry import register_referenced_ids_provider

        register_referenced_ids_provider(_referenced_stored_file_ids)


def _referenced_stored_file_ids():
    """Every stored file a banner still points at, so the cleanup job never
    treats one of them as an orphan."""
    from .models import Banner

    return list(
        Banner.objects.exclude(image_file=None).values_list('image_file_id', flat=True)
    )
