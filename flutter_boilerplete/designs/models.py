from django.db import models

from storage.models import StoredFile


class Category(models.Model):
    label = models.CharField(max_length=100, unique=True)
    # Cloudinary image shown for the category. Optional in the database because
    # categories created before images existed have none.
    image_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    # Lower numbers are listed first; categories with no priority come last.
    priority = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = [models.F('priority').asc(nulls_last=True), 'label']

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
    class DesignType(models.TextChoices):
        TWO_D = '2d', '2D'
        THREE_D = '3d', '3D'

    category = models.ForeignKey(Category, related_name='designs', on_delete=models.PROTECT)
    sub_category = models.ForeignKey(
        SubCategory, related_name='designs', on_delete=models.SET_NULL, null=True, blank=True,
    )
    title = models.CharField(max_length=255)
    # Shown as a 2D/3D toggle in the add/edit form; 2D unless the admin picks 3D.
    design_type = models.CharField(
        max_length=2, choices=DesignType.choices, default=DesignType.TWO_D,
    )
    # Shown as an unchecked-by-default checkbox in the add/edit form.
    is_paid = models.BooleanField(default=False)
    # Required, and must be greater than zero, whenever is_paid is set; null
    # for a free design.
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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
