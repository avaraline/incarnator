# Generated by Django 4.2.1 on 2023-05-15 09:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0016_index_together_migration"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="language",
            field=models.CharField(default=""),
        ),
    ]