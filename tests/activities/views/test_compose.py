import pytest
from django.test.client import Client
from pytest_django.asserts import assertContains

from users.models import Identity


@pytest.mark.django_db
def test_rate_limit(identity: Identity, client_with_user: Client):
    """
    Tests that the posting rate limit comes into force
    """
    # First post should go through
    assert identity.posts.count() == 0
    response = client_with_user.post(
        f"/@{identity.handle}/compose/", data={"text": "post 1", "visibility": "0"}
    )
    assert response.status_code == 302
    assert identity.posts.count() == 1
    # Second should not
    response = client_with_user.post(
        f"/@{identity.handle}/compose/", data={"text": "post 2", "visibility": "0"}
    )
    assertContains(response, "You must wait at least", status_code=200)
    assert identity.posts.count() == 1


@pytest.mark.django_db
def test_compose_poll(client_with_user, identity):
    response = client_with_user.post(
        f"/@{identity.handle}/compose/",
        {
            "text": "Choose one",
            "visibility": "0",
            "poll_options": "First\nSecond",
            "poll_duration": "300",
            "poll_multiple": "on",
            "poll_hide_totals": "on",
        },
    )
    assert response.status_code == 302
    post = identity.posts.get()
    assert post.type == "Question"
    assert post.type_data.mode == "anyOf"
    assert post.type_data.hide_totals
    assert [o.name for o in post.type_data.options] == ["First", "Second"]
    assert post.type_data.end_time is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "options,duration",
    [
        ("One", "300"),
        ("One\nOne", "300"),
        ("One\n\nTwo", "300"),
        ("One\nTwo", "1"),
        ("One\nTwo", ""),
        ("x" * 51 + "\nTwo", "300"),
    ],
)
def test_invalid_poll_does_not_create_post(
    client_with_user, identity, options, duration
):
    response = client_with_user.post(
        f"/@{identity.handle}/compose/",
        {
            "text": "Choose",
            "visibility": "0",
            "poll_options": options,
            "poll_duration": duration,
        },
    )
    assert response.status_code == 200
    assert not identity.posts.exists()
