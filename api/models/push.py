import json

import requests
from django.conf import settings
from django.db import models
from pywebpush import webpush

from core.models import Config
from stator.models import State, StateField, StateGraph, StatorModel

Policy = models.TextChoices(
    "Policy",
    ["all", "followed", "follower", "none"],
)


class NotificationType(models.TextChoices):
    MENTION = "mention", "Mention"
    STATUS = "status", "Post"
    BOOST = "reblog", "Boost"
    FOLLOW = "follow", "Follow"
    FOLLOW_REQUEST = "follow_request", "Follow Request"
    FAVORITE = "favourite", "Favorite"
    POLL = "poll", "Poll"
    UPDATE = "update", "Update"
    ADMIN_SIGNUP = "admin.sign_up", "Account Signup"
    ADMIN_REPORT = "admin.report", "Report"

    def params(self, **kwargs):
        title, body = "", ""
        match self:
            case NotificationType.BOOST:
                title, body = ("Boost", "{handle} boosted your post.")
        return title.format(**kwargs), body.format(**kwargs)


class PushSubscription(models.Model):
    token = models.OneToOneField(
        "api.Token",
        on_delete=models.CASCADE,
        related_name="push_subscription",
    )
    endpoint = models.CharField(max_length=500)
    keys = models.JSONField(blank=True, null=True)
    alerts = models.JSONField(blank=True, null=True)
    policy = models.CharField(
        max_length=8,
        choices=Policy.choices,
        default="all",
    )

    def to_mastodon_json(self):
        return {
            "id": str(self.pk),
            "endpoint": self.endpoint,
            "alerts": self.alerts or {},
            "policy": self.policy,
            "server_key": settings.SETUP.VAPID_PUBLIC_KEY,
        }

    def update(self, alerts: dict, policy: str):
        self.alerts = alerts
        self.policy = policy
        self.save()


class PushNotificationStates(StateGraph):
    sending = State(try_interval=60, force_initial=True)
    sent = State(delete_after=900)
    failed = State(delete_after=60 * 60 * 24)

    sending.transitions_to(sent)
    sending.transitions_to(failed)
    sending.times_out_to(failed, 600)

    @classmethod
    def handle_sending(cls, instance: "PushNotification"):
        if not settings.SETUP.VAPID_PRIVATE_KEY:
            # No VAPID key, no notifications.
            return cls.failed

        try:
            sub: PushSubscription = instance.token.push_subscription
        except PushSubscription.DoesNotExist:
            # Notifications are not configured.
            return cls.failed

        try:
            session = requests.Session()
            session.verify = False
            webpush(
                {"endpoint": sub.endpoint, "keys": sub.keys},
                json.dumps(instance.to_webpush_json()).encode("utf-8"),
                vapid_private_key=settings.SETUP.VAPID_PRIVATE_KEY,
                content_encoding="aesgcm",
                headers={
                    "content-type": "application/octet-stream",
                },
                requests_session=session,
            )
            return cls.sent
        except Exception:
            return


class PushNotification(StatorModel):
    token = models.ForeignKey(
        "api.Token",
        on_delete=models.CASCADE,
        related_name="push_notifications",
    )
    locale = models.CharField(max_length=2, default="en")
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=100)
    body = models.CharField(max_length=500)

    state = StateField(PushNotificationStates)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def to_webpush_json(self):
        return {
            "access_token": self.token.token,
            "preferred_locale": self.locale,
            "notification_id": self.pk,
            "notification_type": self.type,
            "icon": Config.system.site_icon,
            "title": self.title,
            "body": self.body,
        }
