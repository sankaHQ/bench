from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=32, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    version = models.PositiveIntegerField(default=1)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]


class OrderEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        TRANSITIONED = "transitioned", "Transitioned"

    order = models.ForeignKey(Order, related_name="events", on_delete=models.CASCADE)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    from_status = models.CharField(max_length=16, choices=Order.Status.choices)
    to_status = models.CharField(max_length=16, choices=Order.Status.choices)
    version = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]
