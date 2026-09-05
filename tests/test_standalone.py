"""Regression coverage for running independently of the parent application."""

from datetime import timedelta

import pytest
from django.utils import timezone

from activities.models import Post, PostStates
from takahe import __version__
from users.models import PasswordReset, User


@pytest.mark.django_db
def test_signup_in_production(client, config_system, settings, monkeypatch):
    monkeypatch.setattr(settings.SETUP, "ENVIRONMENT", "production")
    config_system.signup_allowed = True

    response = client.post("/auth/signup/", {"email": "new@example.com"})

    assert response.status_code == 200
    assert User.objects.filter(email="new@example.com").exists()
    assert PasswordReset.objects.filter(user__email="new@example.com").exists()


@pytest.mark.django_db
def test_instance_metadata_is_standalone(client, domain, config_system, settings):
    response = client.get("/nodeinfo/2.0/")
    assert response.status_code == 200
    assert response.json()["software"] == {
        "name": "takahe",
        "version": __version__,
    }
    assert response.json()["protocols"] == ["activitypub"]
    for version in (1, 2):
        response = client.get(f"/api/v{version}/instance")
        assert response.status_code == 200
        assert f"Takahe {__version__}" in response.json()["version"]
    assert settings.TAKAHE_USER_AGENT.startswith(f"Takahe/{__version__}")
    assert not hasattr(settings, "NEODB_MQ")


@pytest.mark.django_db
def test_plain_note_ignores_journal_extensions(remote_identity, config_system):
    post = Post.by_ap(
        {
            "id": "https://remote.test/posts/standalone/",
            "type": "Note",
            "attributedTo": remote_identity.actor_uri,
            "content": "A regular status",
            "relatedWith": [{"type": "Review", "content": "External metadata"}],
        },
        create=True,
    )
    assert post.content == "A regular status"
    assert post.type_data is None
    assert "ext_neodb" not in post.to_mastodon_json()


@pytest.mark.django_db
def test_legacy_note_can_be_edited_without_republishing_metadata(
    identity, api_client, config_system
):
    post = Post.create_local(author=identity, content="Original")
    post.type_data = {
        "object": {
            "content": "Stale content",
            "relatedWith": [{"type": "Review"}],
        }
    }
    post.save()

    response = api_client.put(
        f"/api/v1/statuses/{post.pk}",
        content_type="application/json",
        data={"status": "Edited"},
    )

    assert response.status_code == 200
    assert "ext_neodb" not in response.json()
    post.refresh_from_db()
    document = post.to_ap()
    assert document["content"] == "<p>Edited</p>"
    assert "relatedWith" not in document


@pytest.mark.django_db
def test_article_edit_does_not_corrupt_document(identity, api_client, config_system):
    post = Post.create_local(author=identity, content="Article body")
    post.type = Post.Types.article
    post.type_data = {"object": {"name": "Article title", "content": "Article body"}}
    post.save()

    response = api_client.put(
        f"/api/v1/statuses/{post.pk}",
        content_type="application/json",
        data={"status": "Replacement"},
    )

    assert response.status_code == 422
    assert "NeoDB" not in response.json()["error"]
    post.refresh_from_db()
    assert post.content == "<p>Article body</p>"
    assert post.type_data["object"]["name"] == "Article title"


@pytest.mark.django_db
def test_pruning_applies_to_all_remote_software(remote_identity, settings, monkeypatch):
    monkeypatch.setattr(settings.SETUP, "REMOTE_PRUNE_HORIZON", 30)
    remote_identity.domain.nodeinfo = {"protocols": ["activitypub", "neodb"]}
    remote_identity.domain.save()
    post = Post.objects.create(
        author=remote_identity,
        local=False,
        content="Old remote post",
        object_uri="https://remote.test/posts/old/",
    )
    post.created = timezone.now() - timedelta(days=31)
    post_id = post.pk

    assert PostStates.handle_fanned_out(post) == PostStates.deleted_fanned_out
    assert not Post.objects.filter(pk=post_id).exists()
