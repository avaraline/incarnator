from django.shortcuts import get_object_or_404
from hatchway import api_view

from activities.models import Post, PostInteraction
from api import schemas
from api.decorators import scope_required


@scope_required("read:statuses")
@api_view.get
def get_poll(request, id: str) -> schemas.Poll:
    post = get_object_or_404(Post, pk=id, type=Post.Types.question)
    return schemas.Poll.from_post(post, identity=request.identity)


@scope_required("write:statuses")
@api_view.post
def vote_poll(request, id: str, choices: list[int]) -> schemas.Poll:
    post = get_object_or_404(Post, pk=id, type=Post.Types.question)
    PostInteraction.create_votes(post, request.identity, choices)
    post.refresh_from_db()
    return schemas.Poll.from_post(post, identity=request.identity)
