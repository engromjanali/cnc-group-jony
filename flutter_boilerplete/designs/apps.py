from django.apps import AppConfig


class DesignsConfig(AppConfig):
    name = 'designs'

    def ready(self):
        from storage.registry import register_referenced_ids_provider

        register_referenced_ids_provider(_referenced_stored_file_ids)


def _referenced_stored_file_ids():
    from .models import Design

    return list(
        Design.objects.exclude(image_file=None).values_list('image_file_id', flat=True),
    ) + list(
        Design.objects.exclude(design_stored_file=None)
        .values_list('design_stored_file_id', flat=True),
    )
