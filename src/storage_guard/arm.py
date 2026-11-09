"""Minimal ARM adapter for the Storage Accounts Get Properties and Update APIs."""

import json
from collections.abc import Callable
from http.client import HTTPException, HTTPSConnection

from storage_guard.handler import ACCOUNT_ID, StorageError

ARM_HOST = "management.azure.com"
ARM_SCOPE = f"https://{ARM_HOST}/.default"
API_VERSION = "2025-06-01"
MAX_RESPONSE_BYTES = 1024 * 1024


class ArmStorage:
    def __init__(self, get_token: Callable[[], str]) -> None:
        self._get_token = get_token

    def read_public_access(self, account_id: str) -> bool:
        body = self._request("GET", account_id)
        if len(body) > MAX_RESPONSE_BYTES:
            raise StorageError("oversized_response")
        try:
            value = json.loads(body)["properties"]["allowBlobPublicAccess"]
        except (ValueError, KeyError, TypeError):
            raise StorageError("unknown_property") from None
        if not isinstance(value, bool):
            raise StorageError("unknown_property")
        return value

    def block_public_access(self, account_id: str) -> None:
        self._request("PATCH", account_id, {"properties": {"allowBlobPublicAccess": False}})

    def _request(self, method: str, account_id: str, body: dict | None = None) -> bytes:
        if not ACCOUNT_ID.fullmatch(account_id):
            raise StorageError("invalid_account_id")
        headers = {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"

        # HTTPSConnection does not follow redirects or forward the credential to another host.
        connection = HTTPSConnection(ARM_HOST, timeout=8)
        try:
            connection.request(
                method,
                f"{account_id}?api-version={API_VERSION}",
                body=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            response = connection.getresponse()
            if response.status != 200:
                raise StorageError("unexpected_http_status", response.status)
            return response.read(MAX_RESPONSE_BYTES + 1) if method == "GET" else b""
        except (OSError, HTTPException):
            raise StorageError("transport_failure") from None
        finally:
            connection.close()
