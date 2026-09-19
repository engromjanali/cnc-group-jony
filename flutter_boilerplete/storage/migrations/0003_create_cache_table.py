from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # `createcachetable` is not migration-state-aware - it creates the table
    # named in CACHES['default']['LOCATION'] directly - so this just invokes
    # it rather than hand-writing the DDL DatabaseCache expects.
    call_command('createcachetable')


def drop_cache_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS django_cache_table')


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0002_storedfile_provider_storage_key'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
