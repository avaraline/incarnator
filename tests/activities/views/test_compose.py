import datetime
from zoneinfo import ZoneInfo

import pytest
from django.test.client import Client
from django.utils import timezone
from pytest_django.asserts import assertContains

from activities.models import Post, ScheduledStatus
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


@pytest.mark.django_db
def test_schedule_from_compose(identity: Identity, client_with_user: Client):
    response = client_with_user.get(f"/@{identity.handle}/compose/")
    assertContains(response, 'type="datetime-local"')
    assertContains(response, 'name="browser_timezone"')
    tz = ZoneInfo("Asia/Tokyo")
    wall = (timezone.now() + datetime.timedelta(days=1)).astimezone(tz)
    response = client_with_user.post(
        f"/@{identity.handle}/compose/",
        data={
            "text": "later",
            "visibility": str(Post.Visibilities.local_only),
            "scheduled_at": wall.strftime("%Y-%m-%dT%H:%M"),
            "browser_timezone": "Asia/Tokyo",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == f"/@{identity.handle}/scheduled/"
    assert identity.posts.count() == 0
    scheduled = ScheduledStatus.objects.get(author=identity)
    assert scheduled.scheduled_at == wall.replace(second=0, microsecond=0)
    assert scheduled.visibility == Post.Visibilities.local_only

    response = client_with_user.get(f"/@{identity.handle}/scheduled/")
    assertContains(response, "later")

    response = client_with_user.post(
        f"/@{identity.handle}/scheduled/", data={"id": scheduled.pk}
    )
    assert response.status_code == 302
    assert not ScheduledStatus.objects.exists()


@pytest.mark.django_db
def test_schedule_from_compose_too_soon(identity: Identity, client_with_user: Client):
    soon = timezone.now() + datetime.timedelta(minutes=2)
    response = client_with_user.post(
        f"/@{identity.handle}/compose/",
        data={
            "text": "soon",
            "visibility": "0",
            "scheduled_at": soon.strftime("%Y-%m-%dT%H:%M"),
            "browser_timezone": "Not/AZone",
        },
    )
    assertContains(response, "date must be in the future", status_code=200)
    assert not ScheduledStatus.objects.exists()
    assert identity.posts.count() == 0
