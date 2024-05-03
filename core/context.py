from django.conf import settings


def config_context(request):
    return {
        "config": request.config,
        "allow_migration": settings.SETUP.ALLOW_USER_MIGRATION,
        "top_section": request.path.strip("/").split("/")[0],
        "opengraph_defaults": {
            "og:site_name": request.config.site_name,
            "og:type": "website",
            "og:title": request.config.site_name,
            "og:url": request.build_absolute_uri(),
        },
    }
