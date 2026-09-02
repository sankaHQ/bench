import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("number", models.CharField(max_length=32, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("submitted", "Submitted"),
                            ("approved", "Approved"),
                            ("shipped", "Shipped"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("total", models.DecimalField(decimal_places=2, max_digits=10)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="OrderEvent",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("updated", "Updated"),
                            ("transitioned", "Transitioned"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "from_status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("submitted", "Submitted"),
                            ("approved", "Approved"),
                            ("shipped", "Shipped"),
                            ("cancelled", "Cancelled"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("submitted", "Submitted"),
                            ("approved", "Approved"),
                            ("shipped", "Shipped"),
                            ("cancelled", "Cancelled"),
                        ],
                        max_length=16,
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="orders.order",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
    ]
