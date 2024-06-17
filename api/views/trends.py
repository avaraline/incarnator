from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count
from django.http import HttpRequest
from django.utils import timezone

from activities.models import Hashtag, Post
from api import schemas
from api.decorators import scope_required
from core.models import Config
from hatchway import api_view


@scope_required("read")
@api_view.get
def trends_tags(
    request: HttpRequest,
    limit: int = 10,
    offset: int = 0,
) -> list[schemas.Tag]:
    popular_tags = cache.get("trends_tags", None)
    if popular_tags is None:
        popular_tags = Hashtag.popular(limit=100, offset=0)
        cache.set("trends_tags", popular_tags, Config.system.cache_timeout_trends)
    return schemas.Tag.map_from_hashtags(
        popular_tags[offset : offset + limit],
        domain=request.domain,
        identity=request.identity,
    )


@scope_required("read")
@api_view.get
def trends_statuses(
    request: HttpRequest,
    limit: int = 10,
    offset: int = 0,
) -> list[schemas.Status]:
    popular_post_ids = cache.get("trends_statuses", None)
    if popular_post_ids is None:
        since = timezone.now().date() - timedelta(days=7)
        popular_post_ids = list(
            Post.objects.not_hidden()
            .public()
            .filter(author__discoverable=True)
            .filter(published__gte=since)
            .annotate(num_interactions=Count("interactions"))
            .filter(num_interactions__gte=1)
            .order_by("-num_interactions", "-published")
            .values_list("id", flat=True)[:100]
        )
        cache.set(
            "trends_statuses", popular_post_ids, Config.system.cache_timeout_trends
        )
    posts = (
        Post.objects.not_hidden()
        .filter(id__in=popular_post_ids[offset : offset + limit])
        .order_by("-published")
    )
    return schemas.Status.map_from_post(list(posts), request.identity)


@scope_required("read")
@api_view.get
def trends_links(
    request: HttpRequest,
    limit: int = 10,
    offset: int | None = None,
) -> list:
    # We don't implement this yet
    return []
