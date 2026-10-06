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
                ("reference", models.CharField(max_length=30, unique=True)),
                ("customer_note", models.CharField(blank=True, default="", max_length=200)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="OrderItem",
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
                ("sku", models.CharField(max_length=30)),
                ("quantity", models.PositiveIntegerField()),
                ("description", models.CharField(blank=True, default="", max_length=120)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="orders.order",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "unique_together": {("order", "sku")},
            },
        ),
        migrations.CreateModel(
            name="Adjustment",
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
                ("code", models.CharField(max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=8)),
                ("note", models.CharField(blank=True, default="", max_length=100)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="adjustments",
                        to="orders.orderitem",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "unique_together": {("item", "code")},
            },
        ),
    ]
