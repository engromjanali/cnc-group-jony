from django.db import models

from .limits import MAX_QUESTION_LENGTH


class Faq(models.Model):
    """One question and its answer on the app's FAQ screen, written by an
    admin."""

    question = models.CharField(max_length=MAX_QUESTION_LENGTH)
    # Plain text; the app shows it as written, line breaks included.
    answer = models.TextField()
    # Lower numbers come first; equal ones keep the order they were added in.
    order = models.PositiveIntegerField(default=0)
    # Switched-off FAQs are kept for the admin but not shown in the app.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'
        ordering = ['order', 'id']

    def __str__(self):
        return self.question
