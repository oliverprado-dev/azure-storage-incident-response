"""Azure Functions Python v2 entry point. Azure handles Event Grid authentication."""

import logging
import os
from functools import lru_cache

import azure.functions as func
from azure.core.exceptions import AzureError
from azure.identity import ManagedIdentityCredential

from storage_guard.arm import ARM_SCOPE, ArmStorage
from storage_guard.handler import GridEvent, Settings, StorageError, log_decision, process_event

app = func.FunctionApp()


@lru_cache(maxsize=1)
def _arm_storage(client_id: str) -> ArmStorage:
    credential = ManagedIdentityCredential(
        client_id=client_id, connection_timeout=5, read_timeout=5, retry_total=0
    )

    def get_token() -> str:
        try:
            return credential.get_token(ARM_SCOPE).token
        except AzureError:
            raise StorageError("identity_failure") from None

    return ArmStorage(get_token)


@app.function_name(name="GuardStorage")
@app.event_grid_trigger(arg_name="event")
def guard_storage(event: func.EventGridEvent) -> None:
    signal = GridEvent(
        event.id,
        event.topic,
        event.subject,
        event.event_type,
        event.event_time,
        event.data_version,
        event.get_json(),
    )
    try:
        settings = Settings.from_env(os.environ)
        client_id = os.environ.get("GUARD_IDENTITY_CLIENT_ID")
        if not client_id:
            raise ValueError("GUARD_IDENTITY_CLIENT_ID is required")
    except ValueError:
        log_decision(signal, "invalid", "error", "invalid_configuration", level=logging.ERROR)
        raise

    process_event(signal, settings, _arm_storage(client_id))
