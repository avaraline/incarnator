import json
import logging
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.conf import settings
from django.db import connection
from django.utils.http import http_date

from core.files import make_safe_client
from core.ld import canonicalise
from core.signatures import HttpSignature

if TYPE_CHECKING:
    from users.models import Identity

logger = logging.getLogger(__name__)

# Namespace for pg_try_advisory_lock, so the key cannot collide with another
# feature's advisory lock. The second key is derived from the identity id.
ADVISORY_LOCK_NAMESPACE = 0x7AC4
ADVISORY_LOCK_MODULUS = 2**31

# Stator's row lock expires after 300 seconds even if the handler still runs.
# Leave time for in-flight requests and the state transition before it expires.
DEFAULT_DEADLINE = 200.0
# Bound the tail because DNS and slow responses can outlast HTTP timeouts.
# Abandon stuck threads; they hold no handler resources and late Deletes are harmless.
DEFAULT_TAIL_GRACE = 30.0
DEFAULT_CONCURRENCY = 200
# Connect is the term that matters: a black-holed host burns all of it.
DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)


@contextmanager
def identity_broadcast_lock(identity_pk: int) -> Iterator[bool]:
    """Hold a session advisory lock on this handler's thread-local DB connection.
    Always release it: persistent connections otherwise retain the lock indefinitely."""
    key = identity_pk % ADVISORY_LOCK_MODULUS
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, %s)", [ADVISORY_LOCK_NAMESPACE, key]
        )
        acquired = bool(cursor.fetchone()[0])
    try:
        yield acquired
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s, %s)",
                        [ADVISORY_LOCK_NAMESPACE, key],
                    )
            except Exception:
                logger.exception("Could not release broadcast lock for %s", identity_pk)


class DeleteBroadcaster:
    """Broadcast Delete(actor) without queue rows or retries.
    Known peers receive durable FanOut deliveries separately."""

    def __init__(
        self,
        identity: "Identity",
        deadline: float = DEFAULT_DEADLINE,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        tail_grace: float = DEFAULT_TAIL_GRACE,
    ):
        self.identity = identity
        self.deadline = deadline
        self.tail_grace = tail_grace
        self.concurrency = concurrency
        self.timeout = timeout
        self.transport = transport
        # The body is the same for every peer, so it is built once. Only the
        # signed headers differ, because they cover the target and the host.
        self.body = json.dumps(canonicalise(identity.to_delete_ap())).encode("utf8")
        self.digest = HttpSignature.calculate_digest(self.body)
        self.key_id = identity.public_key_id
        # Parsing the PEM is the expensive part of signing, and signed_request
        # repeats it for every single delivery.
        self.private_key = cast(
            rsa.RSAPrivateKey,
            serialization.load_pem_private_key(
                (identity.private_key or "").encode("ascii"), password=None
            ),
        )

    def headers_for(self, uri: str) -> dict[str, str]:
        uri_parts = urlparse(uri)
        headers = {
            "(request-target)": f"post {uri_parts.path}",
            "Host": uri_parts.hostname or "",
            "Date": http_date(),
            "Digest": self.digest,
            "Content-Type": "application/activity+json",
        }
        signed_string = "\n".join(
            f"{name.lower()}: {value}" for name, value in headers.items()
        )
        signature = self.private_key.sign(
            signed_string.encode("utf8"), padding.PKCS1v15(), hashes.SHA256()
        )
        headers["Signature"] = HttpSignature.compile_signature(
            {
                "keyid": self.key_id,
                "headers": list(headers.keys()),
                "signature": signature,
                "algorithm": "rsa-sha256",
            }
        )
        headers["User-Agent"] = settings.TAKAHE_USER_AGENT
        del headers["(request-target)"]
        return headers

    def deliver(self, client: httpx.Client, uri: str) -> bool:
        try:
            response = client.post(
                uri, headers=self.headers_for(uri), content=self.body
            )
        except Exception as error:
            # Best effort: a peer that cannot be reached is simply skipped.
            # It still learns of the deletion when it next pulls the actor.
            logger.debug("Delete broadcast to %s failed: %s", uri, error)
            return False
        # post() does not raise on a 4xx or 5xx, and a peer that answered 401 or
        # 500 has not taken the news.
        if response.status_code >= 400:
            logger.debug(
                "Delete broadcast to %s refused: %s", uri, response.status_code
            )
            return False
        return True

    def send(self, uris: list[str]) -> tuple[int, int]:
        """
        Returns how many were attempted and how many were accepted.
        """
        if settings.SETUP.NO_FEDERATION or not uris:
            return 0, 0
        started = time.monotonic()
        attempted = 0
        delivered = 0
        pending: set[Future[bool]] = set()
        limits = httpx.Limits(max_connections=self.concurrency)

        def collect(done: set[Future[bool]]) -> None:
            nonlocal delivered
            delivered += sum(1 for future in done if future.result())

        with make_safe_client(
            timeout=self.timeout,
            limits=limits,
            transport=self.transport,
            # A redirected POST would arrive with a signature that no longer
            # covers its target, exactly as signed_request avoids for deliveries.
            follow_redirects=False,
        ) as client:

            def remaining() -> float:
                return self.deadline - (time.monotonic() - started)

            pool = ThreadPoolExecutor(max_workers=self.concurrency)
            try:
                for uri in uris:
                    if remaining() <= 0:
                        logger.warning(
                            "Delete broadcast for %s hit its %ss deadline after %s of %s inboxes",
                            self.identity.pk,
                            self.deadline,
                            attempted,
                            len(uris),
                        )
                        break
                    # Submit at most one batch so the deadline bounds requests, not just queueing.
                    if len(pending) >= self.concurrency:
                        done, pending = wait(
                            pending,
                            timeout=remaining(),
                            return_when=FIRST_COMPLETED,
                        )
                        collect(done)
                        if not done:
                            # Everything in flight is stuck and there is no
                            # time left to wait for a slot.
                            continue
                    pending.add(pool.submit(self.deliver, client, uri))
                    attempted += 1
                done, abandoned = wait(pending, timeout=self.tail_grace)
                collect(done)
                if abandoned:
                    logger.warning(
                        "Delete broadcast for %s left %s deliveries unfinished",
                        self.identity.pk,
                        len(abandoned),
                    )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        logger.info(
            "Delete broadcast for %s: %s of %s attempted inboxes accepted it",
            self.identity.pk,
            delivered,
            attempted,
        )
        return attempted, delivered


def broadcast_identity_deletion(
    identity: "Identity", uris: list[str]
) -> tuple[int, int]:
    """
    Best-effort Delete(actor) to inboxes that get no FanOut of their own.
    """
    return DeleteBroadcaster(identity).send(uris)
