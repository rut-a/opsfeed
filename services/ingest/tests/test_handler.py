
import base64
import hashlib
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch


# Fake AWS modules so the handler can be imported without boto3 installed.
fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = MagicMock()
fake_boto3.resource = MagicMock()

fake_botocore = types.ModuleType("botocore")
fake_botocore_exceptions = types.ModuleType("botocore.exceptions")


class FakeClientError(Exception):
    def __init__(self, error_response, operation_name):
        self.response = error_response
        self.operation_name = operation_name
        super().__init__(error_response)


fake_botocore_exceptions.ClientError = FakeClientError
fake_botocore.exceptions = fake_botocore_exceptions

sys.modules["boto3"] = fake_boto3
sys.modules["botocore"] = fake_botocore
sys.modules["botocore.exceptions"] = fake_botocore_exceptions

from services.ingest import handler


class TestIngestHandler(unittest.TestCase):
    def setUp(self):
        self.api_key = "test-api-key"
        self.tenant_id = "tenant-123"
        self.key_hash = hashlib.sha256(
            self.api_key.encode("utf-8")
        ).hexdigest()

        # Pre-fill the cache so this test does not call SSM.
        handler._tenant_map_cache = {
            "mapping": {self.key_hash: self.tenant_id},
            "expires_at": float("inf"),
        }

        self.table = MagicMock()
        handler._table = self.table

        self.event = {
            "specversion": "1.0",
            "id": "evt-001",
            "source": "com.opsfeed.deploy",
            "type": "com.opsfeed.deploy.finished",
            "time": "2026-10-28T10:30:00+02:00",
            "severity": "info",
        }

        self.request = {
            "version": "2.0",
            "headers": {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            "body": json.dumps(self.event),
            "isBase64Encoded": False,
        }

    def test_created_event_uses_tenant_and_utc_day_partition(self):
        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 201)
        self.table.put_item.assert_called_once()

        item = self.table.put_item.call_args.kwargs["Item"]

        # +02:00 converts to 08:30 UTC, so the UTC date is October 28.
        self.assertEqual(item["pk"], "tenant-123#2026-10-28")
        self.assertEqual(
            item["sk"],
            "2026-10-28T08:30:00.000000Z#evt-001",
        )
        self.assertEqual(item["tenant_id"], "tenant-123")
        self.assertEqual(item["id"], "evt-001")
        self.assertEqual(item["severity"], "info")
        self.assertIn("received_at", item)
        self.assertIn("expires_at", item)

        # A conditional put prevents a replay from overwriting an item.
        self.assertEqual(
            self.table.put_item.call_args.kwargs["ConditionExpression"],
            "attribute_not_exists(pk)",
        )
    

    def test_replay_returns_200_duplicate(self):
        self.table.put_item.side_effect = FakeClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "PutItem",
        )

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            json.loads(response["body"])["status"],
            "duplicate",
        )

    def test_missing_api_key_returns_401_without_table_access(self):
        self.request["headers"].pop("Authorization")

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(
            response["headers"]["www-authenticate"],
            "Bearer",
        )
        self.table.put_item.assert_not_called()

    def test_wrong_api_key_returns_401_without_table_access(self):
        self.request["headers"]["Authorization"] = "Bearer wrong-key"

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 401)
        self.table.put_item.assert_not_called()

    def test_tenant_id_in_body_is_rejected(self):
        self.event["tenant_id"] = "attacker-tenant"
        self.request["body"] = json.dumps(self.event)

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 400)
        self.table.put_item.assert_not_called()

        problem = json.loads(response["body"])
        self.assertTrue(
            any(error["field"] == "tenant_id"
                for error in problem["errors"])
        )

    def test_wrong_content_type_returns_415(self):
        self.request["headers"]["Content-Type"] = "text/plain"

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 415)
        self.table.put_item.assert_not_called()

    def test_oversized_body_returns_413(self):
        self.request["body"] = " " * (64 * 1024 + 1)

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 413)
        self.table.put_item.assert_not_called()

    def test_invalid_json_returns_400(self):
        self.request["body"] = '{"specversion": '

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 400)
        self.table.put_item.assert_not_called()

    def test_storage_failure_returns_500(self):
        self.table.put_item.side_effect = FakeClientError(
            {"Error": {"Code": "InternalServerError"}},
            "PutItem",
        )

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 500)
        self.table.put_item.assert_called_once()

    
    def test_ssm_lookup_failure_returns_503(self):
        handler._tenant_map_cache = None

        with patch(
            "services.ingest.handler._load_tenant_map",
            side_effect=RuntimeError("SSM unavailable"),
        ):
            response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(response["headers"]["retry-after"], "5")
        self.table.put_item.assert_not_called()

    def test_base64_encoded_body_is_accepted(self):
        body = json.dumps(self.event).encode("utf-8")
        self.request["body"] = base64.b64encode(body).decode("ascii")
        self.request["isBase64Encoded"] = True

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 201)
        self.table.put_item.assert_called_once()

    def test_cloudevents_content_type_is_accepted(self):
        self.request["headers"]["Content-Type"] = (
            "application/cloudevents+json"
        )

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 201)

    def test_header_names_are_case_insensitive(self):
        self.request["headers"] = {
            "aUtHoRiZaTiOn": f"Bearer {self.api_key}",
            "cOnTeNt-TyPe": "application/json",
        }

        response = handler.handler(self.request, None)

        self.assertEqual(response["statusCode"], 201)



if __name__ == "__main__":
    unittest.main()
