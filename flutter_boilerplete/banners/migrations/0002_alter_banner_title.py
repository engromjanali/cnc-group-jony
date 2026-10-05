from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('banners', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='banner',
            name='title',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
