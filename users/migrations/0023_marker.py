# Generated by Django 4.2.11 on 2024-04-17 03:09

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0022_follow_request"),
    ]

    operations = [
        migrations.CreateModel(
            name="Marker",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("timeline", models.CharField(max_length=100)),
                ("last_read_id", models.CharField(max_length=200)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "identity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="markers",
                        to="users.identity",
                    ),
                ),
            ],
            options={
                "unique_together": {("identity", "timeline")},
            },
        ),
    ]