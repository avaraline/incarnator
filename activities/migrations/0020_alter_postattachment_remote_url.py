# Generated by Django 4.2.8 on 2024-01-06 05:18

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0019_alter_postattachment_focal_x_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="postattachment",
            name="remote_url",
            field=models.CharField(blank=True, max_length=2500, null=True),
        ),
    ]
