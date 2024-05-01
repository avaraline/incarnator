from django.contrib import admin

from api.models import Application, Token


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "website", "created"]
    search_fields = ["name", "website"]


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "identity", "application", "created"]
    autocomplete_fields = ["user", "identity", "application"]
