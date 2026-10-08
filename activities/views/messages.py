"""Identity-scoped web inbox for direct conversations."""

from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.cache import patch_cache_control
from django.views.generic import FormView, ListView

from activities.models import Post, TimelineEvent
from activities.models.conversation import ConversationMembership
from activities.services import PostService, TimelineService
from activities.views.compose import Compose
from core.models import Config
from users.models import Block, Identity
from users.views.base import IdentityViewMixin


class PrivateMessagesMixin(IdentityViewMixin):
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["section"] = "messages"
        return context


class Messages(PrivateMessagesMixin, ListView):
    template_name = "activities/messages.html"
    context_object_name = "conversations"
    paginate_by = 20

    def get_queryset(self):
        return TimelineService(self.identity).conversations()

    def post(self, request, *args, **kwargs):
        try:
            conversation_id = int(request.POST.get("conversation", ""))
        except ValueError:
            raise Http404("Unknown conversation")
        membership = get_object_or_404(
            ConversationMembership,
            identity=self.identity,
            conversation_id=conversation_id,
        )
        action = request.POST.get("action")
        if action == "dismiss":
            membership.dismissed = True
        elif action in {"read", "unread"}:
            membership.unread = action == "unread"
        membership.save(update_fields=["dismissed", "unread", "updated"])
        return redirect("messages", handle=self.identity.handle)


class MessageForm(Compose.form_class):
    recipients = forms.CharField(
        help_text="Space-separated full handles, for example @alice@example.com.",
    )

    def __init__(self, identity, participants=None, *args, **kwargs):
        super().__init__(identity, *args, **kwargs)
        self.participants = participants
        for name in list(self.fields):
            if name not in {"text", "content_warning", "recipients"}:
                del self.fields[name]
        self.fields["text"].widget.attrs.pop("_", None)
        if participants is not None:
            self.fields["recipients"].disabled = True
            self.fields["recipients"].initial = " ".join(
                f"@{p.handle}" for p in participants if p != identity
            )

    def clean_recipients(self):
        if self.participants is not None:
            recipients = set(self.participants) - {self.identity}
        else:
            handles = self.cleaned_data["recipients"].split()
            if len(handles) > 20:
                raise forms.ValidationError("Use at most 20 recipients.")
            recipients = set()
            for handle in handles:
                recipient = Identity.by_handle(handle, fetch=True)
                if recipient is None or recipient == self.identity:
                    raise forms.ValidationError(f"Cannot message {handle}.")
                recipients.add(recipient.resolved)
        if not recipients:
            raise forms.ValidationError("Choose at least one recipient.")
        for recipient in recipients:
            if (
                recipient.deleted
                or not recipient.username
                or not recipient.domain_id
                or recipient.domain.recursively_blocked()
                or Block.objects.active()
                .filter(
                    Q(source=self.identity, target=recipient)
                    | Q(source=recipient, target=self.identity),
                    mute=False,
                )
                .exists()
            ):
                raise forms.ValidationError("A recipient is unavailable.")
        return recipients

    def clean(self):
        data = super().clean()
        if data.get("text") and data.get("recipients"):
            prefix = " ".join(f"@{p.handle}" for p in data["recipients"])
            if len(prefix) + 1 + len(data["text"]) > Config.system.post_length:
                self.add_error(
                    "text",
                    "The message including recipient handles exceeds the post length limit.",
                )
            # Mentions in the body must never silently expand a private audience.
            mentions = Post.mentions_from_content(data["text"], self.identity)
            if mentions - data["recipients"] - {self.identity}:
                self.add_error(
                    "text",
                    "The message mentions someone outside this conversation. Start a new message to include them.",
                )
        return data


class MessageCompose(PrivateMessagesMixin, FormView):
    template_name = "activities/message.html"
    form_class = MessageForm
    membership = None

    def post_identity_setup(self):
        if "conversation_id" in self.kwargs:
            self.membership = get_object_or_404(
                ConversationMembership.objects.select_related(
                    "conversation"
                ).prefetch_related("conversation__participants__domain"),
                identity=self.identity,
                conversation_id=self.kwargs["conversation_id"],
            )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["identity"] = self.identity
        if self.membership:
            kwargs["participants"] = list(
                self.membership.conversation.participants.all()
            )
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.membership:
            conversation = self.membership.conversation
            context["conversation"] = conversation
            posts = (
                PostService.queryset()
                .filter(conversation=conversation)
                .visible_to(self.identity, include_replies=True)
            )
            page = Paginator(posts.order_by("-id"), 50).get_page(
                self.request.GET.get("page")
            )
            context["posts"] = list(reversed(list(page)))
            context["page_obj"] = page
            # Mark read on a successful page view, not on failed submissions.
            if self.request.method == "GET":
                ConversationMembership.objects.filter(pk=self.membership.pk).update(
                    unread=False
                )
        return context

    def form_valid(self, form):
        recipients = form.cleaned_data["recipients"]
        content = (
            " ".join(f"@{p.handle}" for p in sorted(recipients, key=lambda p: p.pk))
            + "\n"
            + form.cleaned_data["text"]
        )
        with transaction.atomic():
            post = Post.create_local(
                author=self.identity,
                content=content,
                summary=form.cleaned_data.get("content_warning"),
                visibility=Post.Visibilities.mentioned,
                reply_to=PostService.queryset()
                .filter(conversation=self.membership.conversation)
                .visible_to(self.identity, include_replies=True)
                .order_by("-id")
                .first()
                if self.membership
                else None,
            )
            TimelineEvent.add_post(self.identity, post)
        return redirect(
            "message", handle=self.identity.handle, conversation_id=post.conversation_id
        )
