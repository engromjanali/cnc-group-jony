from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='storedfile',
            old_name='key',
            new_name='storage_key',
        ),
        # Uniqueness moves to (provider, storage_key) below: an R2 key and a
        # Cloudinary public_id live in separate namespaces.
        migrations.AlterField(
            model_name='storedfile',
            name='storage_key',
            field=models.CharField(max_length=512),
        ),
        # Every row created before this migration was an R2 upload.
        migrations.AddField(
            model_name='storedfile',
            name='provider',
            field=models.CharField(
                choices=[('cloudinary', 'Cloudinary'), ('r2', 'Cloudflare R2')],
                default='r2',
                max_length=16,
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='storedfile',
            constraint=models.UniqueConstraint(
                fields=('provider', 'storage_key'), name='unique_provider_storage_key',
            ),
        ),
    ]
