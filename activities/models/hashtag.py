import re
import time
from datetime import date, timedelta

import urlman
from django.conf import settings
from django.db import connection, models, transaction
from django.utils import timezone

from core.models import Config
from stator.models import State, StateField, StateGraph, StatorModel


class HashtagStates(StateGraph):
    outdated = State(try_interval=300, force_initial=True)
    updated = State(externally_progressed=True)

    outdated.transitions_to(updated)
    updated.transitions_to(outdated)

    @classmethod
    def handle_outdated(cls, instance: "Hashtag"):
        """
        Computes the stats and other things for a Hashtag
        """
        from .post import Post

        posts_query = Post.objects.local_public().tagged_with(instance)
        total = posts_query.count()

        today = timezone.now().date()
        total_today = posts_query.filter(created__date=today).count()
        total_month = posts_query.filter(
            created__year=today.year,
            created__month=today.month,
        ).count()
        total_year = posts_query.filter(
            created__year=today.year,
        ).count()

        history = []
        tagged_posts = Post.objects.not_hidden().tagged_with(instance)
        for i in range(7):
            # Mastodon doesn't include today in history.
            day = today - timedelta(days=i + 1)
            data = tagged_posts.filter(published__date=day).aggregate(
                total=models.Count("id"),
                num_authors=models.Count("author", distinct=True),
            )
            history.append(
                {
                    "day": str(int(time.mktime(day.timetuple()))),
                    "uses": str(data["total"]),
                    "accounts": str(data["num_authors"]),
                }
            )

        instance.stats = {
            "total": total,
            today.isoformat(): total_today,
            today.strftime("%Y-%m"): total_month,
            today.strftime("%Y"): total_year,
            "history": history,
        }
        instance.stats_updated = timezone.now()
        instance.save()

        return cls.updated


class HashtagQuerySet(models.QuerySet):
    def public(self):
        public_q = models.Q(public=True)
        if Config.system.hashtag_unreviewed_are_public:
            public_q |= models.Q(public__isnull=True)
        return self.filter(public_q)

    def hashtag_or_alias(self, hashtag: str):
        return self.filter(
            models.Q(hashtag=hashtag) | models.Q(aliases__contains=hashtag)
        )


class HashtagManager(models.Manager):
    def get_queryset(self):
        return HashtagQuerySet(self.model, using=self._db)

    def public(self):
        return self.get_queryset().public()

    def hashtag_or_alias(self, hashtag: str):
        return self.get_queryset().hashtag_or_alias(hashtag)


class Hashtag(StatorModel):
    MAXIMUM_LENGTH = 100

    # Normalized hashtag without the '#'
    hashtag = models.SlugField(primary_key=True, max_length=100)

    # Friendly display override
    name_override = models.CharField(max_length=100, null=True, blank=True)

    # Should this be shown in the public UI?
    public = models.BooleanField(null=True)

    # State of this Hashtag
    state = StateField(HashtagStates)

    # Metrics for this Hashtag
    stats = models.JSONField(null=True, blank=True)
    # Timestamp of last time the stats were updated
    stats_updated = models.DateTimeField(null=True, blank=True)

    # List of other hashtags that are considered similar
    aliases = models.JSONField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = HashtagManager()

    class urls(urlman.Urls):
        view = "/tags/{self.hashtag}/"
        follow = "/tags/{self.hashtag}/follow/"
        unfollow = "/tags/{self.hashtag}/unfollow/"
        admin = "/admin/hashtags/"
        admin_edit = "{admin}{self.hashtag}/"
        admin_enable = "{admin_edit}enable/"
        admin_disable = "{admin_edit}disable/"
        timeline = "/tags/{self.hashtag}/"

    hashtag_regex = re.compile(r"\B#([a-zA-Z0-9(_)]+\b)(?!;)")

    def save(self, *args, **kwargs):
        self.hashtag = self.hashtag.lstrip("#")
        if self.name_override:
            self.name_override = self.name_override.lstrip("#")
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.name_override or self.hashtag

    @property
    def needs_update(self):
        if self.stats_updated is None:
            return True
        return timezone.now() - self.stats_updated > timedelta(hours=1)

    def __str__(self):
        return self.display_name

    def usage_months(self, num: int = 12) -> dict[date, int]:
        """
        Return the most recent num months of stats
        """
        if not self.stats:
            return {}
        results = {}
        for key, val in self.stats.items():
            parts = key.split("-")
            if len(parts) == 2:
                year = int(parts[0])
                month = int(parts[1])
                results[date(year, month, 1)] = val
        return dict(sorted(results.items(), reverse=True)[:num])

    def usage_days(self, num: int = 7) -> dict[date, int]:
        """
        Return the most recent num days of stats
        """
        if not self.stats:
            return {}
        results = {}
        for key, val in self.stats.items():
            parts = key.split("-")
            if len(parts) == 3:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                results[date(year, month, day)] = val
        return dict(sorted(results.items(), reverse=True)[:num])

    @classmethod
    def popular(cls, days=8, limit=10, offset=None) -> list["Hashtag"]:
        sql = """
            SELECT jsonb_array_elements_text(hashtags) AS tag, count(id) AS uses
            FROM activities_post
            WHERE state NOT IN ('deleted', 'deleted_fanned_out') AND published >= %s
            GROUP BY tag
            ORDER BY uses DESC
            LIMIT %s
            OFFSET %s
        """
        since = timezone.now().date() - timedelta(days=days)
        if offset is None:
            offset = 0
        with connection.cursor() as cur:
            cur.execute(sql, (since, limit, offset))
            names = [r[0] for r in cur.fetchall()]
        # Grab all the popular tags at once.
        tags = {t.hashtag: t for t in cls.objects.filter(hashtag__in=names)}
        # Make sure we return the list in the original order of usage count.
        return [tags[name] for name in names if name in tags]

    @classmethod
    def ensure_hashtag(cls, name, update=None):
        """
        Properly strips/trims/lowercases the hashtag name, and makes sure a Hashtag
        object exists in the database, and returns it.
        """
        name = name.strip().lstrip("#").lower()[: Hashtag.MAXIMUM_LENGTH]
        hashtag, created = cls.objects.get_or_create(hashtag=name)
        if created or update or hashtag.needs_update:
            hashtag.transition_perform(HashtagStates.outdated)
        return hashtag

    @classmethod
    def handle_add_ap(cls, data):
        """
        Handles an incoming Add activity - sent when someone features a Hashtag.

        {
            "type": "Add",
            "actor": "https://hachyderm.io/users/dcw",
            "object": {
                "href": "https://hachyderm.io/@dcw/tagged/incarnator",
                "name": "#incarnator",
                "type": "Hashtag",
            },
            "target": "https://hachyderm.io/users/dcw/collections/featured",
        }
        """

        from users.models import Identity

        target = data.get("target", None)
        if not target:
            return

        with transaction.atomic():
            identity = Identity.by_actor_uri(data["actor"], create=True)
            # Featured tags target the featured collection URI, same as pinned posts.
            if identity.featured_collection_uri != target:
                return

            tag = Hashtag.ensure_hashtag(data["object"]["name"])
            return identity.hashtag_features.get_or_create(hashtag=tag)[0]

    @classmethod
    def handle_remove_ap(cls, data):
        """
        Handles an incoming Remove activity - sent when someone unfeatures a Hashtag.

        {
            "type": "Remove",
            "actor": "https://hachyderm.io/users/dcw",
            "object": {
                "href": "https://hachyderm.io/@dcw/tagged/netneutrality",
                "name": "#netneutrality",
                "type": "Hashtag",
            },
            "target": "https://hachyderm.io/users/dcw/collections/featured",
        }
        """

        from users.models import Identity

        target = data.get("target", None)
        if not target:
            return

        with transaction.atomic():
            identity = Identity.by_actor_uri(data["actor"], create=True)
            # Featured tags target the featured collection URI, same as pinned posts.
            if identity.featured_collection_uri != target:
                return

            tag = Hashtag.ensure_hashtag(data["object"]["name"])
            identity.hashtag_features.filter(hashtag=tag).delete()

    def to_ap(self, domain=None):
        hostname = domain.uri_domain if domain else settings.MAIN_DOMAIN
        return {
            "type": "Hashtag",
            "href": f"https://{hostname}/tags/{self.hashtag}/",
            "name": "#" + self.hashtag,
        }

    def to_add_ap(self, identity):
        """
        Returns the AP JSON to add a featured tag to the given identity.
        """
        return {
            "type": "Add",
            "actor": identity.actor_uri,
            "target": identity.actor_uri + "collections/featured/",
            "object": self.to_ap(domain=identity.domain),
        }

    def to_remove_ap(self, identity):
        """
        Returns the AP JSON to remove a featured tag from the given identity.
        """
        return {
            "type": "Remove",
            "actor": identity.actor_uri,
            "target": identity.actor_uri + "collections/featured/",
            "object": self.to_ap(domain=identity.domain),
        }

    def to_mastodon_json(self, following: bool | None = None, domain=None):
        hostname = domain.uri_domain if domain else settings.MAIN_DOMAIN
        value = {
            "name": self.hashtag,
            "url": f"https://{hostname}/tags/{self.hashtag}/",
            "history": (self.stats or {}).get("history", []),
        }

        if following is not None:
            value["following"] = following

        return value
