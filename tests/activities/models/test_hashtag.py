import pytest
from django.utils import timezone

from activities.models import Hashtag, HashtagStates


def _states() -> dict[str, str]:
    return dict(Hashtag.objects.values_list("hashtag", "state"))


@pytest.mark.django_db
def test_ensure_hashtags(django_assert_num_queries):
    Hashtag.objects.create(
        hashtag="old", state=HashtagStates.updated, stats_updated=timezone.now()
    )

    with django_assert_num_queries(3):
        Hashtag.ensure_hashtags(["#Old", "new1", "NEW1", "new2"], update=True)
    assert _states() == {
        "old": HashtagStates.outdated,
        "new1": HashtagStates.outdated,
        "new2": HashtagStates.outdated,
    }

    Hashtag.objects.filter(hashtag="old").update(state=HashtagStates.updated)
    Hashtag.ensure_hashtags(["old", "new3"])
    states = _states()
    assert states["old"] == HashtagStates.updated
    assert states["new3"] == HashtagStates.outdated
