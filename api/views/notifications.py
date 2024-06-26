from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404

from activities.models import PostInteraction, TimelineEvent
from activities.services import TimelineService
from api import schemas
from api.decorators import scope_required
from api.pagination import MastodonPaginator, PaginatingApiResponse, PaginationResult
from hatchway import ApiResponse, api_view

# Types/exclude_types use weird syntax so we have to handle them manually
NOTIFICATION_TYPES = {
    "status": TimelineEvent.Types.post,
    "favourite": TimelineEvent.Types.liked,
    "reblog": TimelineEvent.Types.boosted,
    "mention": TimelineEvent.Types.mentioned,
    "follow": TimelineEvent.Types.followed,
    "follow_request": TimelineEvent.Types.follow_requested,
    "admin.sign_up": TimelineEvent.Types.identity_created,
}


@scope_required("read:notifications")
@api_view.get
def notifications(
    request: HttpRequest,
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = 20,
    account_id: str | None = None,
) -> ApiResponse[list[schemas.Notification]]:
    requested_types = set(request.GET.getlist("types[]"))
    excluded_types = set(request.GET.getlist("exclude_types[]"))
    if not requested_types:
        requested_types = set(NOTIFICATION_TYPES.keys())
    requested_types.difference_update(excluded_types)
    # Use that to pull relevant events
    queryset = TimelineService(request.identity).notifications(
        [NOTIFICATION_TYPES[r] for r in requested_types if r in NOTIFICATION_TYPES]
    )
    paginator = MastodonPaginator()
    pager: PaginationResult[TimelineEvent] = paginator.paginate(
        queryset,
        min_id=min_id,
        max_id=max_id,
        since_id=since_id,
        limit=limit,
    )
    interactions = PostInteraction.get_event_interactions(
        pager.results,
        request.identity,
    )
    return PaginatingApiResponse(
        [
            schemas.Notification.from_timeline_event(event, interactions=interactions)
            for event in pager.results
        ],
        request=request,
        include_params=["limit", "account_id"],
    )


@scope_required("read:notifications")
@api_view.get
def get_notification(
    request: HttpRequest,
    id: str,
) -> schemas.Notification:
    if not id.isdigit():
        raise Http404
    notification = get_object_or_404(
        TimelineService(request.identity).notifications(
            list(NOTIFICATION_TYPES.values())
        ),
        id=id,
    )
    return schemas.Notification.from_timeline_event(notification)


@scope_required("write:notifications")
@api_view.post
def dismiss_notifications(request: HttpRequest) -> dict:
    TimelineService(request.identity).notifications(
        list(NOTIFICATION_TYPES.values())
    ).update(dismissed=True)

    return {}


@scope_required("write:notifications")
@api_view.post
def dismiss_notification(request: HttpRequest, id: str) -> dict:
    notification = get_object_or_404(
        TimelineService(request.identity).notifications(
            list(NOTIFICATION_TYPES.values())
        ),
        id=id,
    )

    notification.dismissed = True
    notification.save()

    return {}
