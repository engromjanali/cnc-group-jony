from django.db import models

from storage.models import StoredFile


class Category(models.Model):
    label = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['label']

    def __str__(self):
        return self.label


class SubCategory(models.Model):
    category = models.ForeignKey(Category, related_name='sub_categories', on_delete=models.CASCADE)
    label = models.CharField(max_length=100)

    class Meta:
        ordering = ['label']
        unique_together = ('category', 'label')

    def __str__(self):
        return f'{self.category.label} / {self.label}'


class Design(models.Model):
    category = models.ForeignKey(Category, related_name='designs', on_delete=models.PROTECT)
    sub_category = models.ForeignKey(
        SubCategory, related_name='designs', on_delete=models.SET_NULL, null=True, blank=True,
    )
    title = models.CharField(max_length=255)
    # Preview image uploaded straight to Cloudinary. Takes precedence over the
    # legacy `image` / `image_url` fields, which only older designs still use.
    image_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    image = models.ImageField(upload_to='designs/images/', blank=True, null=True)
    image_url = models.URLField(blank=True, default='')
    description = models.TextField(blank=True, default='')
    # Cutting file in private R2. Takes precedence over the legacy
    # `design_file` / `design_file_url` fields, which only older designs use.
    # Downloads always go through a fresh short-lived presigned URL.
    design_stored_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    design_file = models.FileField(upload_to='designs/files/', blank=True, null=True)
    design_file_url = models.URLField(blank=True, default='')
    design_file_name = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
