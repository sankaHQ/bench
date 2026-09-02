from django.db import models


class Account(models.Model):
    name = models.CharField(max_length=60, unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]


class LedgerEntry(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="entries")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    memo = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("entry-created", "Entry created"),
        ("entry-deleted", "Entry deleted"),
        ("transfer", "Transfer"),
    ]

    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    account_id = models.IntegerField()
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
