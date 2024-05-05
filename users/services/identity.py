import concurrent.futures
import logging

import httpx
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.db import models, transaction
from django.template.defaultfilters import linebreaks_filter

from activities.models import (
    FanOut,
    Hashtag,
    Post,
    PostInteraction,
    PostInteractionStates,
)
from core.files import resize_image
from core.html import FediverseHtmlParser
from stator.exceptions import TryAgainLater
from users.models import (
    Block,
    BlockStates,
    Domain,
    Follow,
    FollowStates,
    Identity,
    InboxMessage,
    User,
)

logger = logging.getLogger(__name__)


class IdentityService:
    """
    High-level helper methods for doing things to identities
    """

    def __init__(self, identity: Identity):
        self.identity = identity

    @classmethod
    def create(
        cls,
        user: User,
        username: str,
        domain: Domain,
        name: str,
        discoverable: bool = True,
        indexable: bool = False,
    ) -> Identity:
        identity = Identity.objects.create(
            actor_uri=f"https://{domain.uri_domain}/@{username}@{domain.domain}/",
            username=username,
            domain=domain,
            name=name,
            local=True,
            discoverable=discoverable,
            indexable=indexable,
        )
        identity.users.add(user)
        identity.generate_keypair()
        # Send fanouts to all admin identities
        for admin_identity in cls.admin_identities():
            FanOut.objects.create(
                type=FanOut.Types.identity_created,
                identity=admin_identity,
                subject_identity=identity,
            )
        return identity

    @classmethod
    def admin_identities(cls) -> models.QuerySet[Identity]:
        return Identity.objects.filter(users__admin=True).distinct()

    def following(self) -> models.QuerySet[Identity]:
        return (
            Identity.objects.filter(
                inbound_follows__source=self.identity,
                inbound_follows__state__in=FollowStates.group_active(),
            )
            .not_deleted()
            .distinct()
            .order_by("username")
            .select_related("domain")
        )

    def followers(self) -> models.QuerySet[Identity]:
        return (
            Identity.objects.filter(
                outbound_follows__target=self.identity,
                outbound_follows__state=FollowStates.accepted,
            )
            .not_deleted()
            .distinct()
            .order_by("username")
            .select_related("domain")
        )

    def follow_requests(self) -> models.QuerySet[Identity]:
        return (
            Identity.objects.filter(
                outbound_follows__target=self.identity,
                outbound_follows__state=FollowStates.pending_approval,
            )
            .not_deleted()
            .distinct()
            .order_by("username")
            .select_related("domain")
        )

    def accept_follow_request(self, source_identity):
        existing_follow = Follow.maybe_get(source_identity, self.identity)
        if existing_follow:
            existing_follow.transition_perform(FollowStates.accepting)

    def reject_follow_request(self, source_identity):
        existing_follow = Follow.maybe_get(source_identity, self.identity)
        if existing_follow:
            existing_follow.transition_perform(FollowStates.rejecting)

    def follow(self, target_identity: Identity, boosts=True, notify=False) -> Follow:
        """
        Follows a user (or does nothing if already followed).
        Returns the follow.
        """
        if target_identity == self.identity:
            raise ValueError("You cannot follow yourself")
        return Follow.create_local(
            self.identity, target_identity, boosts=boosts, notify=notify
        )

    def unfollow(self, target_identity: Identity):
        """
        Unfollows a user (or does nothing if not followed).
        """
        if target_identity == self.identity:
            raise ValueError("You cannot unfollow yourself")
        existing_follow = Follow.maybe_get(self.identity, target_identity)
        if existing_follow:
            existing_follow.transition_perform(FollowStates.undone)
            InboxMessage.create_internal(
                {
                    "type": "ClearTimeline",
                    "object": target_identity.pk,
                    "actor": self.identity.pk,
                }
            )

    def block(self, target_identity: Identity) -> Block:
        """
        Blocks a user.
        """
        if target_identity == self.identity:
            raise ValueError("You cannot block yourself")
        self.unfollow(target_identity)
        self.reject_follow_request(target_identity)
        block = Block.create_local_block(self.identity, target_identity)
        InboxMessage.create_internal(
            {
                "type": "ClearTimeline",
                "actor": self.identity.pk,
                "object": target_identity.pk,
                "fullErase": True,
            }
        )
        return block

    def unblock(self, target_identity: Identity):
        """
        Unlocks a user
        """
        if target_identity == self.identity:
            raise ValueError("You cannot unblock yourself")
        existing_block = Block.maybe_get(self.identity, target_identity, mute=False)
        if existing_block and existing_block.active:
            existing_block.transition_perform(BlockStates.undone)

    def mute(
        self,
        target_identity: Identity,
        duration: int = 0,
        include_notifications: bool = False,
    ) -> Block:
        """
        Mutes a user.
        """
        if target_identity == self.identity:
            raise ValueError("You cannot mute yourself")
        return Block.create_local_mute(
            self.identity,
            target_identity,
            duration=duration or None,
            include_notifications=include_notifications,
        )

    def unmute(self, target_identity: Identity):
        """
        Unmutes a user
        """
        if target_identity == self.identity:
            raise ValueError("You cannot unmute yourself")
        existing_block = Block.maybe_get(self.identity, target_identity, mute=True)
        if existing_block and existing_block.active:
            existing_block.transition_perform(BlockStates.undone)

    def relationships(self, from_identity: Identity):
        """
        Returns a dict of any active relationships from the given identity.
        """
        return {
            "outbound_follow": Follow.maybe_get(
                from_identity, self.identity, require_active=True
            ),
            "inbound_follow": Follow.maybe_get(
                self.identity, from_identity, require_active=True
            ),
            "outbound_block": Block.maybe_get(
                from_identity, self.identity, mute=False, require_active=True
            ),
            "inbound_block": Block.maybe_get(
                self.identity, from_identity, mute=False, require_active=True
            ),
            "outbound_mute": Block.maybe_get(
                from_identity, self.identity, mute=True, require_active=True
            ),
        }

    def sync_pins(self, object_uris):
        if not object_uris or self.identity.domain.blocked:
            return

        with transaction.atomic():
            for object_uri in object_uris:
                try:
                    post = Post.by_object_uri(object_uri, fetch=True)
                    PostInteraction.objects.get_or_create(
                        type=PostInteraction.Types.pin,
                        identity=self.identity,
                        post=post,
                        state__in=PostInteractionStates.group_active(),
                    )
                except MultipleObjectsReturned as exc:
                    logger.exception("%s on %s", exc, object_uri)
                    pass
                except Post.DoesNotExist:
                    # ignore 404s...
                    pass
                except TryAgainLater:
                    # don't wait for it now, it'll be synced on next refresh
                    pass
            for removed in PostInteraction.objects.filter(
                type=PostInteraction.Types.pin,
                identity=self.identity,
                state__in=PostInteractionStates.group_active(),
            ).exclude(post__object_uri__in=object_uris):
                removed.transition_perform(PostInteractionStates.undone_fanned_out)

    @transaction.atomic
    def sync_tags(self, tags):
        featured = []
        for name in tags:
            hashtag = Hashtag.ensure_hashtag(name)
            self.identity.hashtag_features.get_or_create(hashtag=hashtag)
            featured.append(hashtag)
        self.identity.hashtag_features.exclude(hashtag__in=featured).delete()

    def mastodon_json_relationship(self, from_identity: Identity):
        """
        Returns a Relationship object for the from_identity's relationship
        with this identity.
        """
        relationships = self.relationships(from_identity)
        return {
            "id": str(self.identity.pk),
            "following": (
                relationships["outbound_follow"] is not None
                and relationships["outbound_follow"].accepted
            ),
            "followed_by": (
                relationships["inbound_follow"] is not None
                and relationships["inbound_follow"].accepted
            ),
            "showing_reblogs": (
                relationships["outbound_follow"] is not None
                and relationships["outbound_follow"].boosts
            ),
            "notifying": (
                relationships["outbound_follow"] is not None
                and relationships["outbound_follow"].notify
            ),
            "languages": [],
            "blocking": relationships["outbound_block"] is not None,
            "blocked_by": relationships["inbound_block"] is not None,
            "muting": relationships["outbound_mute"] is not None,
            "muting_notifications": False,
            "requested": (
                relationships["outbound_follow"] is not None
                and relationships["outbound_follow"].state
                == FollowStates.pending_approval
            ),
            "domain_blocking": False,
            "endorsed": False,
            "note": (
                relationships["outbound_follow"]
                and relationships["outbound_follow"].note
                or ""
            ),
        }

    def set_summary(self, summary: str):
        """
        Safely sets a summary and turns linebreaks into HTML
        """
        if summary:
            self.identity.summary = FediverseHtmlParser(linebreaks_filter(summary)).html
        else:
            self.identity.summary = None
        self.identity.save()

    def set_icon(self, file):
        """
        Sets the user's avatar image
        """
        self.identity.icon.save(
            file.name,
            resize_image(file, size=(400, 400)),
        )

    def set_image(self, file):
        """
        Sets the user's header image
        """
        self.identity.image.save(
            file.name,
            resize_image(file, size=(1500, 500)),
        )

    @classmethod
    def handle_internal_add_follow(cls, payload):
        """
        Handles an inbox message saying we need to follow a handle

        Message format:
        {
            "type": "AddFollow",
            "source": "90310938129083",
            "target_handle": "andrew@aeracode.org",
            "boosts": true,
        }
        """
        # Retrieve ourselves
        self = cls(Identity.objects.get(pk=payload["source"]))
        # Get the remote end (may need a fetch)
        username, domain = payload["target_handle"].split("@")
        target_identity = Identity.by_username_and_domain(username, domain, fetch=True)
        if target_identity is None:
            raise ValueError(f"Cannot find identity to follow: {target_identity}")
        # Follow!
        self.follow(target_identity=target_identity, boosts=payload.get("boosts", True))

    @classmethod
    def handle_internal_sync_actor(cls, payload):
        """
        Handles an inbox message saying we need to sync featured posts and tags, and
        fetch the follower/following/outbox counts.

        Message format:
        {
            "type": "SyncActor",
            "identity": "90310938129083",
        }
        """
        actor = Identity.objects.get(pk=payload["identity"])
        self = cls(actor)
        stats = {"last_status_at": None}
        pipeline = [
            (
                actor.fetch_pinned_post_uris,
                actor.featured_collection_uri,
                self.sync_pins,
            ),
            (
                actor.fetch_featured_tags,
                actor.featured_tags_uri,
                self.sync_tags,
            ),
            (
                actor.fetch_collection,
                actor.followers_uri,
                lambda x: stats.setdefault("followers_count", x[0]),
            ),
            (
                actor.fetch_collection,
                actor.following_uri,
                lambda x: stats.setdefault("following_count", x[0]),
            ),
            (
                actor.fetch_collection,
                actor.outbox_uri,
                lambda x: stats.setdefault("statuses_count", x[0]),
            ),
        ]
        future_actions = {}
        with httpx.Client(
            timeout=settings.SETUP.REMOTE_TIMEOUT,
            headers={"User-Agent": settings.TAKAHE_USER_AGENT},
        ) as client:
            # TODO: move this to a global pool, or use stator executor
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(pipeline)
            ) as pool:
                # Do all the fetching in threads using a single client
                for fn, url, action in pipeline:
                    future_actions[pool.submit(fn, client, url)] = action
                # Re-submit the updates to happen in threads as well
                for f in concurrent.futures.as_completed(future_actions):
                    pool.submit(future_actions[f], f.result())
                # Wait for everything to finish
                pool.shutdown()
        logger.info("SYNC %s", stats)
        actor.stats = stats
        actor.save(update_fields=["stats"])
