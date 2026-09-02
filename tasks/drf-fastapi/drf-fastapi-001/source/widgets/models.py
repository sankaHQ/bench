from django.db import models


class Widget(models.Model):
    name = models.CharField(max_length=80)
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]
