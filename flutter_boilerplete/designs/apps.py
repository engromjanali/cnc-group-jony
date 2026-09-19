from django.apps import AppConfig


class DesignsConfig(AppConfig):
    name = 'designs'

    def ready(self):
        from storage.registry import register_referenced_ids_provider

        register_referenced_ids_provider(_referenced_stored_file_ids)


def _referenced_stored_file_ids():
    """Every stored file a design or category still points at, so the cleanup
    job never treats one of them as an orphan."""
    from .models import Category, Design

    def ids(queryset, field):
        return list(queryset.exclude(**{field: None}).values_list(f'{field}_id', flat=True))

    return (
        ids(Design.objects, 'image_file')
        + ids(Design.objects, 'design_stored_file')
        + ids(Category.objects, 'image_file')
    )
