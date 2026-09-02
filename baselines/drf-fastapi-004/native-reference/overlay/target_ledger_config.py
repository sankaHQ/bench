"""A ledger AppConfig that does not connect the source signal receivers."""

from django.apps import AppConfig


class PlainLedgerConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "ledger"
