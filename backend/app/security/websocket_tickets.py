"""Single-process, short-lived WebSocket ticket storage."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from threading import Lock

WEBSOCKET_SUBPROTOCOL = "relay.v1"
TICKET_SUBPROTOCOL_PREFIX = "relay-ticket."


def ticket_from_subprotocols(header_value: str | None) -> str | None:
    """Extract the offered ticket protocol without putting credentials in the URL."""
    if not header_value:
        return None
    protocols = [protocol.strip() for protocol in header_value.split(",")]
    if WEBSOCKET_SUBPROTOCOL not in protocols:
        return None
    for protocol in protocols:
        if protocol.startswith(TICKET_SUBPROTOCOL_PREFIX):
            ticket = protocol[len(TICKET_SUBPROTOCOL_PREFIX):]
            return ticket or None
    return None


@dataclass(frozen=True)
class ConsumedWebSocketTicket:
    user_id: int
    authentication_expires_at: datetime


@dataclass(frozen=True)
class _TicketRecord:
    user_id: int
    ticket_expires_at: datetime
    authentication_expires_at: datetime


class WebSocketTicketStore:
    """Atomically issue and consume opaque tickets in this process only."""

    def __init__(self, ttl_seconds: int = 30, max_tickets: int = 10000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_tickets = max_tickets
        self._tickets: dict[str, _TicketRecord] = {}
        self._lock = Lock()

    @staticmethod
    def _key(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def issue(self, user_id: int, authentication_expires_at: datetime) -> tuple[str, int]:
        now = self._now()
        authentication_expires_at = authentication_expires_at.astimezone(timezone.utc)
        expires_at = min(
            now + timedelta(seconds=self.ttl_seconds), authentication_expires_at
        )
        if expires_at <= now:
            raise ValueError("The authenticated session is expired.")

        ticket = secrets.token_urlsafe(32)
        key = self._key(ticket)
        with self._lock:
            self._remove_expired(now)
            if len(self._tickets) >= self.max_tickets:
                raise RuntimeError("WebSocket ticket store is at capacity.")
            self._tickets[key] = _TicketRecord(
                user_id=user_id,
                ticket_expires_at=expires_at,
                authentication_expires_at=authentication_expires_at,
            )
        return ticket, max(1, int((expires_at - now).total_seconds()))

    def consume(self, ticket: str | None) -> ConsumedWebSocketTicket | None:
        if not ticket:
            return None
        now = self._now()
        key = self._key(ticket)
        with self._lock:
            self._remove_expired(now)
            record = self._tickets.pop(key, None)
        if (
            record is None
            or record.ticket_expires_at <= now
            or record.authentication_expires_at <= now
        ):
            return None
        return ConsumedWebSocketTicket(
            user_id=record.user_id,
            authentication_expires_at=record.authentication_expires_at,
        )

    def _remove_expired(self, now: datetime) -> None:
        expired = [
            key for key, record in self._tickets.items()
            if record.ticket_expires_at <= now
            or record.authentication_expires_at <= now
        ]
        for key in expired:
            self._tickets.pop(key, None)


websocket_ticket_store = WebSocketTicketStore()
