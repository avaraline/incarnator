# Generated by Django 4.2.11 on 2024-05-02 19:57

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0027_identity_stats"),
    ]

    operations = [
        migrations.AddField(
            model_name="follow",
            name="notify",
            field=models.BooleanField(
                default=False, help_text="Notify about posts from this user"
            ),
        ),
    ]
