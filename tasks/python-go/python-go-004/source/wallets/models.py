from django.db import models


class Wallet(models.Model):
    tenant = models.CharField(max_length=20)
    name = models.CharField(max_length=40)
    balance = models.DecimalField(max_digits=9, decimal_places=2)


class Transfer(models.Model):
    tenant = models.CharField(max_length=20)
    idempotency_key = models.CharField(max_length=40)
    source = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="outgoing")
    destination = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="incoming")
    amount = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="tenant_transfer_key"
            )
        ]


class AuditEvent(models.Model):
    transfer = models.OneToOneField(Transfer, on_delete=models.PROTECT)
    event = models.CharField(max_length=20)
