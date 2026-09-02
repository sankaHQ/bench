from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [
        migrations.CreateModel(
            name="Widget",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("quantity", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["id"]},
        )
    ]
