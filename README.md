Incarnator is a fork of [Takahē](https://github.com/jointakahe/takahe), a fediverse
server for microblogging. You can read more about Takahē from
[the website](https://jointakahe.org/), or check the original
[README](https://github.com/jointakahe/takahe/blob/main/README.md).

This fork has a number of changes/additions:

* Upgraded to pydantic 2.0
* Reworked settings nav to show all identities
* Markers API
* Lists API
* Blocks API
* Languages API
* Featured tags
* Calculated and stored identity stats (post/follow counts)
* Push notifications
* Support for the `notify` attribute on follows
* Hashtag history
* Trending hashtags and statuses
* Fetch follow/post counts for non-local identities
* Relay support
* Conversations API
* Report API
* Quote posts (FEP-044f)
* Group actor support
* ActivityPub replies collection sync
* Preview cards
* Poll creation, voting, edits, and expiry notifications
* ActivityPub inbox forwarding, Lemmy interoperability, and collection feature authorization
* Article and media object rendering with preview cards
* Poll and Direct-message UI
* Opt-in Mastodon streaming over WebSocket and Server-Sent Events

Requires Python 3.14+ and PostgreSQL 14+. See [installation](docs/installation.rst),
[development](docs/contributing.rst), and [upgrade notes](docs/releases/next.rst).
