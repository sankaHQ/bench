from django.db import models


class Entry(models.Model):
    code = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    state = models.CharField(
        max_length=16,
        choices=[("draft", "Draft"), ("published", "Published")],
        default="draft",
    )

    class Meta:
        ordering = ["id"]
