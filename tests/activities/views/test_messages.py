import pytest
from django.urls import reverse

from activities.models import Post
from activities.models.conversation import ConversationMembership
from users.models import Block

pytestmark = pytest.mark.django_db


def url(identity, name="messages", **kwargs):
    return reverse(name, kwargs={"handle": identity.handle, **kwargs})


def test_send_and_read_message(client_with_user, identity, other_identity):
    response = client_with_user.post(
        url(identity, "message_new"),
        {
            "recipients": f"@{other_identity.handle}",
            "text": "Hello privately",
        },
    )
    assert response.status_code == 302
    post = Post.objects.get(author=identity)
    assert post.visibility == Post.Visibilities.mentioned
    assert set(post.mentions.all()) == {other_identity}
    assert post.conversation_id
    page = client_with_user.get(response.url)
    assert page.status_code == 200
    assert b"Hello privately" in page.content
    assert "no-store" in page.headers["Cache-Control"]
    incoming = client_with_user.get(url(other_identity))
    assert b"Unread" in incoming.content
    client_with_user.get(
        url(other_identity, "message", conversation_id=post.conversation_id)
    )
    assert not ConversationMembership.objects.get(identity=other_identity).unread
    listing = client_with_user.get(url(identity))
    assert b"Hello privately" in listing.content


def test_reply_cannot_expand_audience(
    client_with_user, identity, other_identity, identity2
):
    post = Post.create_local(
        author=other_identity,
        content=f"@{identity.handle} Hello",
        visibility=Post.Visibilities.mentioned,
    )
    response = client_with_user.post(
        url(identity, "message", conversation_id=post.conversation_id),
        {
            "text": f"@{identity2.handle} secret",
            "recipients": f"@{identity2.handle}",
        },
    )
    assert response.status_code == 200
    assert b"outside this conversation" in response.content
    assert Post.objects.count() == 1


def test_nonparticipant_cannot_read_or_dismiss(
    client_with_user, identity, other_identity, identity2
):
    post = Post.create_local(
        author=other_identity,
        content=f"@{identity2.handle} secret",
        visibility=Post.Visibilities.mentioned,
    )
    assert (
        client_with_user.get(
            url(identity, "message", conversation_id=post.conversation_id)
        ).status_code
        == 404
    )
    assert (
        client_with_user.post(
            url(identity), {"action": "dismiss", "conversation": post.conversation_id}
        ).status_code
        == 404
    )
    assert b"secret" not in client_with_user.get(url(identity)).content


def test_blocked_recipient_cannot_be_messaged(
    client_with_user, identity, other_identity
):
    Block.objects.create(
        source=other_identity, target=identity, mute=False, state="sent"
    )
    response = client_with_user.post(
        url(identity, "message_new"),
        {
            "recipients": other_identity.handle,
            "text": "Blocked message",
        },
    )
    assert response.status_code == 200
    assert b"unavailable" in response.content
    assert not Post.objects.exists()


def test_conversation_actions_are_private_and_identity_scoped(
    client_with_user, identity, other_identity
):
    post = Post.create_local(
        author=identity,
        content=f"@{other_identity.handle} hi",
        visibility=Post.Visibilities.mentioned,
    )
    response = client_with_user.post(
        url(identity), {"action": "dismiss", "conversation": post.conversation_id}
    )
    assert response.status_code == 302
    assert "no-store" in response.headers["Cache-Control"]
    assert ConversationMembership.objects.get(identity=identity).dismissed
    assert not ConversationMembership.objects.get(identity=other_identity).dismissed
    assert not client_with_user.get(url(identity)).context["conversations"]
