# Generated by Django 4.2.11 on 2024-05-01 19:54

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0003_token_push_subscription"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="token",
            name="push_subscription",
        ),
        migrations.CreateModel(
            name="PushSubscription",
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
                ("endpoint", models.CharField(max_length=500)),
                ("keys", models.JSONField(blank=True, null=True)),
                ("alerts", models.JSONField(blank=True, null=True)),
                (
                    "policy",
                    models.CharField(
                        choices=[
                            ("all", "All"),
                            ("followed", "Followed"),
                            ("follower", "Follower"),
                            ("none", "None"),
                        ],
                        default="all",
                        max_length=8,
                    ),
                ),
                (
                    "token",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="push_subscription",
                        to="api.token",
                    ),
                ),
            ],
        ),
    ]