import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=60, unique=True)),
                ("balance", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("entry-created", "Entry created"),
                            ("entry-deleted", "Entry deleted"),
                            ("transfer", "Transfer"),
                        ],
                        max_length=20,
                    ),
                ),
                ("account_id", models.IntegerField()),
                ("delta", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("memo", models.CharField(blank=True, default="", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="ledger.account",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
    ]
