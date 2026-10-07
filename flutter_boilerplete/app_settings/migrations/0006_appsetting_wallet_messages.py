from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('app_settings', '0005_appsetting_allowed_file_extensions_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='appsetting',
            name='wallet_warning_text',
            field=models.CharField(blank=True, default='', max_length=2000),
        ),
        migrations.AddField(
            model_name='appsetting',
            name='wallet_offer_text',
            field=models.CharField(blank=True, default='', max_length=2000),
        ),
    ]
