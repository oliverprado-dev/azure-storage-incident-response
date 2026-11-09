import json
import unittest
from unittest.mock import Mock, patch

from storage_guard.arm import API_VERSION, ARM_HOST, ArmStorage
from storage_guard.handler import StorageError

ACCOUNT = (
    "/subscriptions/00000000-0000-0000-0000-000000000001"
    "/resourceGroups/rg-asir-demo01/providers/Microsoft.Storage/storageAccounts/asirlabdemo01"
)


class ArmTest(unittest.TestCase):
    def setUp(self):
        connection_type = self.enterContext(patch("storage_guard.arm.HTTPSConnection"))
        self.connection_type = connection_type
        self.connection = connection_type.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.get_token = Mock(return_value="synthetic-test-token")
        self.arm = ArmStorage(self.get_token)

    def test_get_reads_boolean_with_fixed_arm_host(self):
        self.response.read.return_value = b'{"properties":{"allowBlobPublicAccess":true}}'
        self.assertIs(self.arm.read_public_access(ACCOUNT), True)
        self.connection_type.assert_called_once_with(ARM_HOST, timeout=8)
        self.connection.request.assert_called_once_with(
            "GET",
            f"{ACCOUNT}?api-version={API_VERSION}",
            body=None,
            headers={"Authorization": "Bearer synthetic-test-token", "Accept": "application/json"},
        )
        self.connection.close.assert_called_once()

    def test_patch_body_contains_only_the_monitored_property(self):
        self.arm.block_public_access(ACCOUNT)
        args, kwargs = self.connection.request.call_args
        self.assertEqual(args, ("PATCH", f"{ACCOUNT}?api-version={API_VERSION}"))
        self.assertEqual(
            json.loads(kwargs["body"]), {"properties": {"allowBlobPublicAccess": False}}
        )
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_absent_null_or_string_property_is_an_error(self):
        for body in (
            b"not JSON",
            b'{"properties":{}}',
            b'{"properties":{"allowBlobPublicAccess":null}}',
            b'{"properties":{"allowBlobPublicAccess":"false"}}',
        ):
            with self.subTest(body=body), self.assertRaisesRegex(StorageError, "unknown_property"):
                self.response.read.return_value = body
                self.arm.read_public_access(ACCOUNT)

    def test_redirect_and_permission_status_are_errors(self):
        for status in (302, 403):
            with self.subTest(status=status), self.assertRaises(StorageError) as raised:
                self.response.status = status
                self.arm.read_public_access(ACCOUNT)
            self.assertEqual(raised.exception.status_code, status)
        self.assertEqual(self.connection.request.call_count, 2)
        self.response.read.assert_not_called()

    def test_untrusted_id_fails_before_fetching_a_token(self):
        with self.assertRaisesRegex(StorageError, "invalid_account_id"):
            self.arm.block_public_access(f"{ACCOUNT}?bad=1")
        self.get_token.assert_not_called()
        self.connection_type.assert_not_called()
