from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "ledger"

    def ready(self) -> None:
        from ledger import signals  # noqa: F401
