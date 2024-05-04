from django.db.models import Count
from django.http import HttpRequest

from activities.models import Hashtag, Post
from api import schemas
from api.decorators import scope_required
from hatchway import api_view


@scope_required("read")
@api_view.get
def trends_tags(
    request: HttpRequest,
    limit: int = 10,
    offset: int | None = None,
) -> list[schemas.Tag]:
    return [
        schemas.Tag.from_hashtag(t) for t in Hashtag.popular(limit=limit, offset=offset)
    ]


@scope_required("read")
@api_view.get
def trends_statuses(
    request: HttpRequest,
    limit: int = 10,
    offset: int | None = None,
) -> list[schemas.Status]:
    if offset is None:
        offset = 0
    posts = list(
        Post.objects.not_hidden()
        .visible_to(request.identity)
        .annotate(num_interactions=Count("interactions"))
        .order_by("-num_interactions", "-created")[offset : offset + limit]
    )
    return schemas.Status.map_from_post(posts, request.identity)


@scope_required("read")
@api_view.get
def trends_links(
    request: HttpRequest,
    limit: int = 10,
    offset: int | None = None,
) -> list:
    # We don't implement this yet
    return []
