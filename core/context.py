from django.conf import settings

from core.models import Config


def config_context(request):
    return {
        "config": Config.system,
        "config_domain": request.domain.config_domain if request.domain else None,
        "allow_migration": settings.SETUP.ALLOW_USER_MIGRATION,
        "top_section": request.path.strip("/").split("/")[0],
        "opengraph_defaults": {
            "og:site_name": Config.system.site_name,
            "og:type": "website",
            "og:title": Config.system.site_name,
            "og:url": request.build_absolute_uri(),
        },
    }
