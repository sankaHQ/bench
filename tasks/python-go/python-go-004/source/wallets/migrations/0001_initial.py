import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Transfer",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("tenant", models.CharField(max_length=20)),
                ("idempotency_key", models.CharField(max_length=40)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=9)),
            ],
        ),
        migrations.CreateModel(
            name="Wallet",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("tenant", models.CharField(max_length=20)),
                ("name", models.CharField(max_length=40)),
                ("balance", models.DecimalField(decimal_places=2, max_digits=9)),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("event", models.CharField(max_length=20)),
                (
                    "transfer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT, to="wallets.transfer"
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="transfer",
            name="destination",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="incoming",
                to="wallets.wallet",
            ),
        ),
        migrations.AddField(
            model_name="transfer",
            name="source",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="outgoing",
                to="wallets.wallet",
            ),
        ),
        migrations.AddConstraint(
            model_name="transfer",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key"), name="tenant_transfer_key"
            ),
        ),
    ]
