import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import call, create_autospec

from storage_guard.handler import GridEvent, Settings, Storage, StorageError, process_event

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "resource-write-success.json"


class HandlerTest(unittest.TestCase):
    def setUp(self):
        [self.payload] = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.event = GridEvent.from_payload(self.payload)
        self.account_id = self.payload["data"]["resourceUri"]
        self.dry_run = Settings(self.account_id)
        self.enforce = Settings(self.account_id, remediation_enabled=True)
        self.storage = create_autospec(Storage, instance=True, spec_set=True)

    def process(self, settings=None, event=None):
        with self.assertLogs("storage_guard.handler", level="INFO") as captured:
            result = process_event(event or self.event, settings or self.dry_run, self.storage)
        self.assertEqual(len(captured.records), 1)
        log = json.loads(captured.records[0].getMessage())
        self.assertEqual(result, log["result"])
        return log

    def test_compliant_account_reads_without_writing_even_in_enforce_mode(self):
        self.storage.read_public_access.return_value = False
        log = self.process(self.enforce)
        self.assertEqual(log["decision"], "no_action")
        self.assertEqual(log["result"], "compliant")
        self.assertIs(log["before"], False)
        self.assertEqual(self.storage.mock_calls, [call.read_public_access(self.account_id)])

    def test_drift_in_dry_run_records_decision_without_writing(self):
        self.storage.read_public_access.return_value = True
        log = self.process()
        self.assertEqual(log["result"], "would_remediate")
        self.assertEqual(log["mode"], "dry-run")
        self.assertEqual(log["event_id"], self.payload["id"])
        self.assertEqual(log["resource_id"], self.payload["subject"])
        self.assertEqual(log["correlation_id"], self.payload["data"]["correlationId"])
        self.assertEqual(self.storage.mock_calls, [call.read_public_access(self.account_id)])

    def test_enforcement_patches_once_and_verifies_with_a_second_get(self):
        self.storage.read_public_access.side_effect = [True, False]
        log = self.process(self.enforce)
        self.assertEqual(log["result"], "verified")
        self.assertIs(log["before"], True)
        self.assertIs(log["after"], False)
        self.assertEqual(
            self.storage.mock_calls,
            [
                call.read_public_access(self.account_id),
                call.block_public_access(self.account_id),
                call.read_public_access(self.account_id),
            ],
        )

    def test_duplicate_event_reads_again_and_does_not_patch_a_compliant_account(self):
        self.storage.read_public_access.side_effect = [True, False, False]
        self.assertEqual(self.process(self.enforce)["result"], "verified")
        self.assertEqual(self.process(self.enforce)["result"], "compliant")
        self.storage.block_public_access.assert_called_once_with(self.account_id)
        self.assertEqual(self.storage.read_public_access.call_count, 3)

    def test_event_from_our_own_patch_observes_the_already_compliant_state(self):
        self.storage.read_public_access.side_effect = [True, False, False]
        self.assertEqual(self.process(self.enforce)["result"], "verified")
        correction = replace(self.event, event_id="correction-event")
        self.assertEqual(self.process(self.enforce, correction)["result"], "compliant")
        self.storage.block_public_access.assert_called_once_with(self.account_id)

    def test_late_duplicate_can_correct_new_drift(self):
        self.storage.read_public_access.side_effect = [True, False, True, False]
        self.assertEqual(self.process(self.enforce)["result"], "verified")
        self.assertEqual(self.process(self.enforce)["result"], "verified")
        self.assertEqual(self.storage.block_public_access.call_count, 2)

    def test_rejects_other_accounts_children_topics_and_mismatched_resource_uri(self):
        other_id = self.account_id.replace("asirlabdemo01", "otheraccount")
        other_data = {**self.payload["data"], "resourceUri": other_id}
        for event in (
            replace(self.event, subject=other_id, data=other_data),
            replace(self.event, subject=f"{self.account_id}/blobServices/default"),
            replace(self.event, data=other_data),
            replace(self.event, topic=f"{self.event.topic}-other"),
            replace(self.event, data={**self.payload["data"], "subscriptionId": "other"}),
        ):
            with self.subTest(event=event):
                self.assertEqual(self.process(self.enforce, event)["result"], "out_of_scope")
        self.assertEqual(self.storage.mock_calls, [])

    def test_invalid_event_and_unsupported_operation_are_acknowledged_without_azure_calls(self):
        for event, expected in (
            (replace(self.event, data=[]), "invalid_event"),
            (replace(self.event, event_id=None), "invalid_event"),
            (replace(self.event, event_time=None), "invalid_event"),
            (replace(self.event, data_version="999"), "unsupported_data_version"),
            (
                replace(self.event, event_type="Microsoft.Resources.ResourceWriteFailure"),
                "unsupported_event_type",
            ),
            (
                replace(
                    self.event,
                    data={**self.payload["data"], "operationName": "Microsoft.Storage/listKeys"},
                ),
                "unsupported_operation",
            ),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(self.process(self.enforce, event)["result"], expected)
        self.assertEqual(self.storage.mock_calls, [])

    def test_read_permission_error_is_logged_and_raised_without_patch(self):
        self.storage.read_public_access.side_effect = StorageError("unexpected_http_status", 403)
        with (
            self.assertLogs("storage_guard.handler", level="ERROR") as captured,
            self.assertRaises(StorageError),
        ):
            process_event(self.event, self.enforce, self.storage)
        log = json.loads(captured.records[0].getMessage())
        self.assertEqual(log["decision"], "error")
        self.assertEqual(log["result"], "arm_error")
        self.assertEqual(log["phase"], "read")
        self.assertEqual(log["status_code"], 403)
        self.storage.block_public_access.assert_not_called()

    def test_write_permission_error_is_logged_and_raised_without_success(self):
        self.storage.read_public_access.return_value = True
        self.storage.block_public_access.side_effect = StorageError("unexpected_http_status", 403)
        with (
            self.assertLogs("storage_guard.handler", level="ERROR") as captured,
            self.assertRaises(StorageError),
        ):
            process_event(self.event, self.enforce, self.storage)
        log = json.loads(captured.records[0].getMessage())
        self.assertEqual(log["phase"], "patch")
        self.assertEqual(log["status_code"], 403)
        self.storage.read_public_access.assert_called_once_with(self.account_id)

    def test_retry_after_ambiguous_patch_result_observes_the_live_state(self):
        self.storage.read_public_access.side_effect = [True, False]
        self.storage.block_public_access.side_effect = StorageError("transport_failure")
        with (
            self.assertLogs("storage_guard.handler", level="ERROR"),
            self.assertRaises(StorageError),
        ):
            process_event(self.event, self.enforce, self.storage)
        self.assertEqual(self.process(self.enforce)["result"], "compliant")
        self.storage.block_public_access.assert_called_once_with(self.account_id)

    def test_write_is_only_reported_as_success_if_follow_up_get_confirms_it(self):
        self.storage.read_public_access.side_effect = [True, True]
        with (
            self.assertLogs("storage_guard.handler", level="ERROR") as captured,
            self.assertRaisesRegex(StorageError, "verification_failed"),
        ):
            process_event(self.event, self.enforce, self.storage)
        log = json.loads(captured.records[0].getMessage())
        self.assertEqual(log["phase"], "verify")
        self.assertIs(log["after"], True)

    def test_settings_require_an_exact_account_id_and_explicit_true(self):
        env = {"LAB_STORAGE_ACCOUNT_ID": self.account_id}
        self.assertFalse(Settings.from_env(env).remediation_enabled)
        self.assertTrue(
            Settings.from_env({**env, "REMEDIATION_ENABLED": "true"}).remediation_enabled
        )
        for flag in ("yes", "TRUE", "1", ""):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                Settings.from_env({**env, "REMEDIATION_ENABLED": flag})
        for account_id in ("", f"{self.account_id}?unsafe=query", f"{self.account_id}/x"):
            with self.subTest(account_id=account_id), self.assertRaises(ValueError):
                Settings(account_id)
