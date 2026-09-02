from django.db import models


class Order(models.Model):
    reference = models.CharField(max_length=30, unique=True)
    customer_note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["id"]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    sku = models.CharField(max_length=30)
    quantity = models.PositiveIntegerField()
    description = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["id"]
        unique_together = [("order", "sku")]


class Adjustment(models.Model):
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="adjustments")
    code = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    note = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["id"]
        unique_together = [("item", "code")]
