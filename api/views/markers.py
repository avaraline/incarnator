from django.http import HttpRequest

from api import schemas
from api.decorators import scope_required
from pydantic import ConfigDict
from hatchway import Schema, api_view


class MarkerSchema(Schema):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    last_read_id: str

class PostMarkersSchema(Schema):
    home: MarkerSchema | None = None;
    notifications: MarkerSchema | None = None;

@scope_required("read:statuses")
@api_view.get
def markers(request: HttpRequest) -> dict[str, schemas.Marker]:
    timelines = request.PARAMS.get("timeline[]", [])
    if not isinstance(timelines, list):
        timelines = [timelines]
    data = {}
    for m in request.identity.markers.filter(timeline__in=timelines):
        data[m.timeline] = schemas.Marker.from_marker(m)
    return data


@scope_required("write:statuses")
@api_view.post
def set_markers(request: HttpRequest, details: PostMarkersSchema) -> dict[str, schemas.Marker]:
    markers = {}
    for timeline, defaults in details.model_dump(exclude_none=True).items():
        marker, created = request.identity.markers.get_or_create(
            timeline=timeline,
            defaults=defaults
        )
        if not created:
            marker.last_read_id = defaults["last_read_id"]
            marker.save()
        markers[timeline] = schemas.Marker.from_marker(marker)
    return markers
