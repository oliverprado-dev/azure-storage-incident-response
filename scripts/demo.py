"""Replay synthetic Event Grid signals through the same handler deployed on Azure."""

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from storage_guard.handler import GridEvent, Settings, process_event


@dataclass
class SimulatedStorage:
    account_id: str
    public_access: bool = False
    writes: int = 0

    def read_public_access(self, account_id: str) -> bool:
        if account_id != self.account_id:
            raise ValueError("Conta fora do laboratório simulado")
        return self.public_access

    def block_public_access(self, account_id: str) -> None:
        self.read_public_access(account_id)
        self.public_access = False
        self.writes += 1


def show_state(phase: str, storage: SimulatedStorage) -> None:
    print(
        json.dumps(
            {
                "kind": "simulated_state",
                "phase": phase,
                "allowBlobPublicAccess": storage.public_access,
                "containerPublicAccess": "None",
                "publicNetworkAccess": "Disabled",
                "remediationWrites": storage.writes,
            },
            separators=(",", ":"),
        )
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "resource-write-success.json"
    [operator_write] = json.loads(fixture.read_text(encoding="utf-8"))
    account_id = operator_write["data"]["resourceUri"]
    event = GridEvent.from_payload(operator_write)
    storage = SimulatedStorage(account_id)

    show_state("initial", storage)
    storage.public_access = True
    show_state("operator_drift", storage)
    print(json.dumps({"kind": "synthetic_event", "event": operator_write}, separators=(",", ":")))

    process_event(event, Settings(account_id), storage)
    show_state("after_dry_run", storage)

    # Explicitly replay the signal after enabling enforcement in the simulator.
    active = Settings(account_id, remediation_enabled=True)
    process_event(event, active, storage)
    process_event(event, active, storage)  # Duplicate delivery.
    correction = {
        **operator_write,
        "id": "00000000-0000-4000-8000-000000000102",
        "eventTime": "2026-01-08T12:00:02Z",
        "data": {
            **operator_write["data"],
            "correlationId": "00000000-0000-4000-8000-000000000202",
        },
    }
    print(json.dumps({"kind": "synthetic_event", "event": correction}, separators=(",", ":")))
    process_event(GridEvent.from_payload(correction), active, storage)
    show_state("final", storage)
    if storage.public_access or storage.writes != 1:
        raise SystemExit("Falha na verificação final da demonstração")


if __name__ == "__main__":
    main()
