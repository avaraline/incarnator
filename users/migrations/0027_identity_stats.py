# Generated by Django 4.2.11 on 2024-04-30 13:19

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0026_identity_featured_tags_uri_hashtagfeature"),
    ]

    operations = [
        migrations.AddField(
            model_name="identity",
            name="stats",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
