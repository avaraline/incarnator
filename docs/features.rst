Features
========

Takahē is currently in development, so it does not yet have all the features
of a full ActivityPub server.

Currently, it supports:

* A web UI (which can be installed as a PWA as well)
* Mastodon-compatible client applications (beta support)
* Posts with content warnings and visibilities including a local-only option
* Creating polls through Compose or a client, voting, hidden totals, and expiry notifications
* Direct conversations through Messages or the client API
* Optional live client updates over WebSocket and Server-Sent Events
* Rich post formatting with lists, blockquotes, and code blocks
* Lists, relays, quotes, and trending hashtags/statuses through client APIs
* Editing post content
* Viewing images, videos and other post attachments
* Uploading images and attaching image captions
* Replies, loading reply threads, boosts and likes
* Following, blocking, muting, and disabling boosts from specific users
* Mentioned, liked, boosted and followed notifications
* Following and unfollowing, and you-were-followed notifications
* Home, local, federated, user, and hashtag timelines
* Full profile pages with images, metadata and links
* RSS feeds for users' public posts
* Custom emoji support
* Searching for users, hashtags and posts by URL
* Multiple domain support
* Multiple identity support (per user account)
* Moderation report system and queue
* Server announcements system
* Server defederation (blocking)
* Signup flow, including auto-cap by user numbers and invite system
* Password reset via email
* Bookmarks
* Markers

Features planned for releases up to 1.0:

* Video upload support
* Hashtag explore page/API
* Manual approval of followers
* IP and email domain banning
* Two-factor authentication (TOTP and WebAuthn)
* Metadata verification support

Features that may make it into 1.0, or might be further out:

* Filters
* Scheduling posts
* Mastodon-compatible account migration target/source

Features on the long-term roadmap:

* "Since you were gone" optional algorithmic timeline
* Seamless transfer from a Mastodon installation

Web composition and messages
----------------------------

Select an identity in Settings, then open Compose. Poll options are entered one
per line, with an expiry, optional multiple choices, and optional hidden totals.
Polls cannot include an image. Existing polls can be voted on from post pages;
use a compatible client to edit a poll or upload multiple attachments.

Messages opens that identity's inbox. Use full handles to start a conversation.
Replies keep the same participants and reject mentions that would expand the
audience. Reading a conversation marks it read; the inbox can mark it unread or
dismiss it. Dismissal hides only your inbox entry, and a new message brings it
back. Messages are delivered only to participants' servers; they are not
end-to-end encrypted. Block and visibility rules also apply to streamed events.
