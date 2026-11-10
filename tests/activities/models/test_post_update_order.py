"""An inbound Update older than the stored version does not rewrite the post."""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from activities.models import Post
from users.models import Identity


def _note(remote_identity: Identity, content: str, **dates) -> dict:
    return {
        "id": "https://remote.test/test-actor/posts/1",
        "type": "Note",
        "attributedTo": remote_identity.actor_uri,
        "content": f"<p>{content}</p>",
        "published": "2026-01-01T00:00:00Z",
        **dates,
    }


@pytest.mark.django_db
def test_older_update_is_skipped(remote_identity: Identity):
    Post.by_ap(
        _note(remote_identity, "new", updated="2026-01-03T00:00:00Z"), create=True
    )

    post = Post.by_ap(
        _note(remote_identity, "old", updated="2026-01-02T00:00:00Z"), update=True
    )

    post.refresh_from_db()
    assert "new" in post.content
    assert post.edited == datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)


@pytest.mark.django_db
def test_equal_and_newer_updates_apply(remote_identity: Identity):
    Post.by_ap(
        _note(remote_identity, "first", updated="2026-01-02T00:00:00Z"), create=True
    )

    post = Post.by_ap(
        _note(remote_identity, "same", updated="2026-01-02T00:00:00Z"), update=True
    )
    post.refresh_from_db()
    assert "same" in post.content

    post = Post.by_ap(
        _note(remote_identity, "newer", updated="2026-01-04T00:00:00Z"), update=True
    )
    post.refresh_from_db()
    assert "newer" in post.content
    assert post.edited == datetime.datetime(2026, 1, 4, tzinfo=datetime.UTC)


@pytest.mark.django_db
def test_update_locks_the_post(remote_identity: Identity):
    Post.by_ap(
        _note(remote_identity, "first", updated="2026-01-02T00:00:00Z"), create=True
    )

    with CaptureQueriesContext(connection) as ctx:
        Post.by_ap(
            _note(remote_identity, "second", updated="2026-01-03T00:00:00Z"),
            update=True,
        )

    assert any("FOR UPDATE" in q["sql"] for q in ctx.captured_queries)


@pytest.mark.django_db
def test_update_without_dates_compared_by_published(remote_identity: Identity):
    """An unedited post resent without `updated` (e.g. poll tallies) applies."""
    Post.by_ap(_note(remote_identity, "first"), create=True)

    post = Post.by_ap(_note(remote_identity, "tally"), update=True)

    post.refresh_from_db()
    assert "tally" in post.content
