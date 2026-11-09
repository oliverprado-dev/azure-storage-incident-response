"""Validate Event Grid signals and reconcile the authorized account's live state."""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

WRITE_SUCCESS = "Microsoft.Resources.ResourceWriteSuccess"
STORAGE_WRITE = "Microsoft.Storage/storageAccounts/write"
ACCOUNT_ID = re.compile(
    r"/subscriptions/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
    r"/providers/Microsoft[.]Storage/storageAccounts/[a-z0-9]{3,24}",
    re.ASCII | re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    account_id: str
    remediation_enabled: bool = False

    def __post_init__(self) -> None:
        if not ACCOUNT_ID.fullmatch(self.account_id):
            raise ValueError("LAB_STORAGE_ACCOUNT_ID must be a full storage account ARM ID")

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Settings":
        flag = environ.get("REMEDIATION_ENABLED", "false")
        if flag not in {"true", "false"}:
            raise ValueError("REMEDIATION_ENABLED must be true or false")
        return cls(environ.get("LAB_STORAGE_ACCOUNT_ID", ""), remediation_enabled=flag == "true")

    @property
    def mode(self) -> str:
        return "enforce" if self.remediation_enabled else "dry-run"


@dataclass(frozen=True)
class GridEvent:
    event_id: object
    topic: object
    subject: object
    event_type: object
    event_time: object
    data_version: object
    data: object

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "GridEvent":
        """Decode the wire shape used by the local fixtures."""
        event_time = payload.get("eventTime")
        if isinstance(event_time, str):
            try:
                event_time = datetime.fromisoformat(event_time)
            except ValueError:
                event_time = None
        return cls(
            payload.get("id"),
            payload.get("topic"),
            payload.get("subject"),
            payload.get("eventType"),
            event_time,
            payload.get("dataVersion"),
            payload.get("data"),
        )


class StorageError(RuntimeError):
    """Safe to log. Carries a stable reason and an optional ARM HTTP status."""

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class Storage(Protocol):
    def read_public_access(self, account_id: str) -> bool: ...

    def block_public_access(self, account_id: str) -> None: ...


def _bounded_text(value: object) -> str | None:
    return value[:512] if isinstance(value, str) else None


def log_decision(
    event: GridEvent,
    mode: str,
    decision: str,
    result: str,
    *,
    level: int = logging.INFO,
    **details: object,
) -> str:
    data = event.data if isinstance(event.data, dict) else {}
    LOGGER.log(
        level,
        "%s",
        json.dumps(
            {
                "kind": "storage_public_access_guard",
                "event_id": _bounded_text(event.event_id),
                "resource_id": _bounded_text(event.subject),
                "correlation_id": _bounded_text(data.get("correlationId")),
                "mode": mode,
                "decision": decision,
                "result": result,
                **details,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    return result


def _reject_reason(event: GridEvent, account_id: str) -> str | None:
    if not (
        isinstance(event.event_id, str)
        and len(event.event_id) <= 128
        and event.event_id.strip()
        and isinstance(event.topic, str)
        and isinstance(event.subject, str)
        and isinstance(event.event_type, str)
        and isinstance(event.event_time, datetime)
        and event.event_time.utcoffset() is not None
        and isinstance(event.data_version, str)
        and isinstance(event.data, dict)
    ):
        return "invalid_event"

    if event.event_type != WRITE_SUCCESS:
        return "unsupported_event_type"
    if event.data_version != "2":
        return "unsupported_data_version"

    data = event.data
    fields = ("operationName", "resourceUri", "resourceProvider", "status", "subscriptionId")
    if any(not isinstance(data.get(field), str) or not data[field] for field in fields):
        return "invalid_event"
    if data["operationName"].casefold() != STORAGE_WRITE.casefold():
        return "unsupported_operation"
    if data["resourceProvider"].casefold() != "microsoft.storage" or (
        data["status"].casefold() != "succeeded"
    ):
        return "invalid_event"

    authorized = account_id.casefold()
    topic = authorized.split("/providers/", 1)[0]
    if (
        event.subject.casefold() != authorized
        or data["resourceUri"].casefold() != authorized
        or event.topic.casefold() != topic
        or data["subscriptionId"].casefold() != topic.split("/")[2]
    ):
        return "out_of_scope"
    return None


def process_event(event: GridEvent, settings: Settings, storage: Storage) -> str:
    mode = settings.mode
    if rejection := _reject_reason(event, settings.account_id):
        level = logging.INFO if rejection == "out_of_scope" else logging.WARNING
        return log_decision(event, mode, "ignore", rejection, level=level)

    # The event is a signal. The configured ID, never the payload, addresses ARM.
    account_id = settings.account_id
    phase = "read"
    before = None
    after = None
    try:
        before = storage.read_public_access(account_id)
        if before is False:
            return log_decision(event, mode, "no_action", "compliant", before=False)
        if before is not True:
            raise StorageError("unknown_property")
        if not settings.remediation_enabled:
            return log_decision(event, mode, "detect", "would_remediate", before=True)

        phase = "patch"
        storage.block_public_access(account_id)
        phase = "verify"
        after = storage.read_public_access(account_id)
        if after is not False:
            raise StorageError("verification_failed")
        return log_decision(event, mode, "remediate", "verified", before=True, after=False)
    except StorageError as error:
        log_decision(
            event,
            mode,
            "error",
            "arm_error",
            level=logging.ERROR,
            phase=phase,
            reason=error.reason,
            status_code=error.status_code,
            before=before,
            after=after,
        )
        raise
