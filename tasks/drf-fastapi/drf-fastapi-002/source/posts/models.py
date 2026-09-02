from django.conf import settings
from django.db import models


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    title = models.CharField(max_length=100)
    body = models.CharField(max_length=400, blank=True, default="")

    class Meta:
        ordering = ["id"]
