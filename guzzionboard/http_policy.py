"""The request policy of a locally running workstation.

Three checks, in order: the ``Host`` header must name an address this server
was actually bound to (a browser talking to a rebound DNS name sends the
attacker's name, not ours), any ``Origin`` must be this same workstation
(browsers send one on every cross-origin request, so this is what stops
another page you already have open from pulsing relays on a connected
motorcycle), and - inside the desktop shell - every ``/api/`` call must carry
the token that launch generated.

Requests with no ``Origin`` at all (curl, the app's own test suite, the Python
client in ``--selftest``) are allowed: this policy exists to stop browsers, not
to lock the operator out of their own tool.

This lives outside :mod:`guzzionboard.server` so the policy can be read and
tested without importing the 105-route API module, and so the answer to "what
may reach this API?" is one short file rather than a section of a large one.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from . import resources

#: Host names the workstation answers to. Anything else is refused: the API
#: can energise actuators, so it must not be reachable through a name that a
#: remote page could make resolve here (DNS rebinding).
LOOPBACK_HOST_NAMES = {"127.0.0.1", "localhost", "::1"}

#: Header the desktop window's bridge uses to prove it was handed this
#: launch's token (the name lives in :mod:`guzzionboard.resources` because the
#: shell has to send it too). A query parameter is accepted as well, for the
#: one API call a page cannot attach headers to (``navigator.sendBeacon`` on
#: unload).
TOKEN_HEADER = resources.TOKEN_HEADER
TOKEN_QUERY = "token"


class RequestGuard:
    """The loopback request policy of a locally running workstation.

    Three checks, in order: the ``Host`` header must name loopback (a browser
    talking to a rebound DNS name sends the attacker's name, not ours), any
    ``Origin`` must be this same workstation (browsers send one on every
    cross-origin request, so this is what stops another page you have open
    from talking to a connected motorcycle), and - inside the desktop shell -
    every ``/api/`` call must carry the token that launch generated.

    Requests with no ``Origin`` at all (curl, the app's own test suite, the
    Python client in ``--selftest``) are allowed: this policy exists to stop
    browsers, not to lock the operator out of their own tool.
    """

    def __init__(self, *, token: str | None = None,
                 hosts=LOOPBACK_HOST_NAMES) -> None:
        self.token = token or None
        #: ``None`` means "any name this server is reached by", which is only
        #: right when the operator explicitly bound a non-loopback address.
        self.hosts = None if hosts is None else {h.lower() for h in hosts}

    # -- pieces ----------------------------------------------------------
    @staticmethod
    def host_name(host: str | None) -> str | None:
        if not host:
            return None
        try:
            name = urlsplit(f"//{host}").hostname
        except ValueError:
            return None
        return name.lower() if name else None

    def origin_allowed(self, origin: str, host: str | None) -> bool:
        if origin.lower() == "null":       # file://, sandboxed frames
            return False
        try:
            parts = urlsplit(origin)
            # ``urlsplit`` itself does not validate the port; accessing
            # ``.port`` raises ValueError for "http://host:abc/" or an
            # out-of-range port. A malformed Origin is a refusal, never an
            # exception that escapes the guard.
            origin_port = self._port(parts)
            host_port = self._port(urlsplit(f"//{host or ''}"))
        except ValueError:
            return False
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        if parts.netloc.lower() == (host or "").lower():
            return True
        # `localhost:8080` posting to a window opened as `127.0.0.1:8080` is
        # the same workstation; a different port is a different origin.
        return (
            (parts.hostname or "").lower() in (self.hosts or set())
            and origin_port == host_port
        )

    @staticmethod
    def _port(parts) -> int:
        if parts.port:
            return parts.port
        return 443 if parts.scheme == "https" else 80

    def check(self, *, command: str, path: str, host: str | None, origin: str | None,
              header_token: str | None = None, query_token: str | None = None):
        """``None`` when the request may proceed, else ``(status, message)``."""
        name = self.host_name(host)
        if name is None:
            return 403, "missing Host header"
        if self.hosts is not None and name not in self.hosts:
            return 403, (
                f"this workstation answers loopback names only; {name!r} is not "
                "one of them (open http://127.0.0.1/... instead)"
            )
        if origin and not self.origin_allowed(origin, host):
            return 403, (
                f"refused a request from origin {origin!r}: this API drives "
                "hardware and only answers the window it serves"
            )
        if self.token and path.startswith("/api/"):
            supplied = header_token or query_token or ""
            if not secrets.compare_digest(str(supplied), self.token):
                return 403, (
                    "this launch's session token is missing or wrong; reload the "
                    "window it opened"
                )
        return None


def loopback_guard(*, token: str | None = None) -> RequestGuard:
    """The guard used by both the console server and the desktop shell."""
    return RequestGuard(token=token)


def _binds_loopback(host: str) -> bool:
    return RequestGuard.host_name(host) in LOOPBACK_HOST_NAMES


def guard_for_bind(host: str, *, token: str | None = None) -> RequestGuard:
    """A guard that matches the address the operator asked us to bind.

    Loopback binds get the strict host list. An explicit non-loopback bind is
    a decision the operator already made (a workshop laptop on the LAN), so
    the host check is relaxed there - but a request from *another web origin*
    is still refused, because that is the check that keeps a random page in a
    browser from pulsing relays on a connected motorcycle.
    """
    if _binds_loopback(host):
        return RequestGuard(token=token)
    return RequestGuard(token=token, hosts=None)
