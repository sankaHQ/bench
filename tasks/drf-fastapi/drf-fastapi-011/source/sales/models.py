from django.db import models


class Account(models.Model):
    class Region(models.TextChoices):
        NORTH = "north", "North"
        SOUTH = "south", "South"
        WEST = "west", "West"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    region = models.CharField(max_length=16, choices=Region.choices)

    class Meta:
        ordering = ["code"]


class Transaction(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        POSTED = "posted", "Posted"

    account = models.ForeignKey(
        Account,
        related_name="transactions",
        on_delete=models.CASCADE,
    )
    reference = models.CharField(max_length=40, unique=True)
    state = models.CharField(max_length=16, choices=State.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["id"]
