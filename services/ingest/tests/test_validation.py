import unittest

from services.ingest.validation import ValidationError, validate_event


class TestValidateEvent(unittest.TestCase):
    def setUp(self):
        self.minimal_event = {
            "specversion": "1.0",
            "id": "evt-001",
            "source": "com.opsfeed.deploy",
            "type": "com.opsfeed.deploy.finished",
            "time": "2026-10-28T10:30:00Z",
        }

    def test_minimal_event_gets_default_severity(self):
        result = validate_event(self.minimal_event)

        self.assertEqual(result["severity"], "info")
        self.assertEqual(
            result["time"],
            "2026-10-28T10:30:00.000000Z",
        )

    def test_full_event_maps_every_field(self):
        event = {
            **self.minimal_event,
            "subject": "payment-api",
            "severity": "warning",
            "correlationid": "req-123",
            "datacontenttype": "application/json",
            "data": {"message": "Slow response", "duration_ms": 450},
        }

        result = validate_event(event)

        self.assertEqual(result["specversion"], "1.0")
        self.assertEqual(result["id"], "evt-001")
        self.assertEqual(result["source"], "com.opsfeed.deploy")
        self.assertEqual(result["type"], "com.opsfeed.deploy.finished")
        self.assertEqual(result["time"], "2026-10-28T10:30:00.000000Z")
        self.assertEqual(result["subject"], "payment-api")
        self.assertEqual(result["severity"], "warning")
        self.assertEqual(result["correlationid"], "req-123")
        self.assertEqual(result["datacontenttype"], "application/json")
        self.assertEqual(
            result["data"],
            {"message": "Slow response", "duration_ms": 450},
        )

    def test_offset_time_is_converted_to_utc(self):
        event = {
            **self.minimal_event,
            "time": "2026-10-28T10:30:00+02:00",
        }

        result = validate_event(event)

        self.assertEqual(
            result["time"],
            "2026-10-28T08:30:00.000000Z",
        )

    def test_fractional_seconds_are_normalized_to_six_digits(self):
        short = {
            **self.minimal_event,
            "time": "2026-10-28T10:30:00.12Z",
        }
        long = {
            **self.minimal_event,
            "time": "2026-10-28T10:30:00.123456789Z",
        }

        self.assertEqual(
            validate_event(short)["time"],
            "2026-10-28T10:30:00.120000Z",
        )
        self.assertEqual(
            validate_event(long)["time"],
            "2026-10-28T10:30:00.123456Z",
        )

    def test_bad_severity_names_allowed_values_and_received_value(self):
        event = {**self.minimal_event, "severity": "urgent"}

        with self.assertRaises(ValidationError) as context:
            validate_event(event)

        message = str(context.exception)
        self.assertIn("urgent", message)
        for allowed in ("info", "warning", "error", "critical"):
            self.assertIn(allowed, message)

    def test_multiple_problems_are_reported_together(self):
        event = {
            "specversion": "2.0",
            "source": "",
            "type": "NOT A VALID TYPE",
            "time": "2026-10-28T10:30:00",
            "severity": "urgent",
            "tenant_id": "tenant-123",
            "mystery": "value",
        }

        with self.assertRaises(ValidationError) as context:
            validate_event(event)

        errors = context.exception.errors
        fields = {error["field"] for error in errors}

        self.assertIn("specversion", fields)
        self.assertIn("id", fields)
        self.assertIn("source", fields)
        self.assertIn("type", fields)
        self.assertIn("time", fields)
        self.assertIn("severity", fields)
        self.assertIn("tenant_id", fields)
        self.assertIn("mystery", fields)
        self.assertGreaterEqual(len(errors), 8)

    def test_tenant_id_is_rejected(self):
        event = {**self.minimal_event, "tenant_id": "tenant-123"}

        with self.assertRaises(ValidationError) as context:
            validate_event(event)

        self.assertTrue(
            any(
                error["field"] == "tenant_id"
                for error in context.exception.errors
            )
        )

    def test_unknown_attribute_is_rejected(self):
        event = {**self.minimal_event, "debug": True}

        with self.assertRaises(ValidationError) as context:
            validate_event(event)

        self.assertTrue(
            any(
                error["field"] == "debug"
                for error in context.exception.errors
            )
        )

    def test_bad_type_is_rejected(self):
        for invalid_type in (
            "Deploy.Finished",
            "deploy",
            "com..deploy",
            "com.opsfeed Deploy",
            "com.123deploy.finished",
        ):
            with self.subTest(event_type=invalid_type):
                event = {**self.minimal_event, "type": invalid_type}

                with self.assertRaises(ValidationError):
                    validate_event(event)

    def test_timestamp_without_timezone_is_rejected(self):
        event = {
            **self.minimal_event,
            "time": "2026-10-28T10:30:00",
        }

        with self.assertRaises(ValidationError) as context:
            validate_event(event)

        self.assertIn("time", str(context.exception))

    def test_invalid_calendar_time_is_rejected(self):
        event = {
            **self.minimal_event,
            "time": "2026-02-30T10:30:00Z",
        }

        with self.assertRaises(ValidationError):
            validate_event(event)

    def test_non_object_data_is_rejected(self):
        for data in ("message", ["message"], 42, None):
            with self.subTest(data=data):
                event = {**self.minimal_event, "data": data}

                with self.assertRaises(ValidationError):
                    validate_event(event)

    def test_non_object_body_is_rejected(self):
        for raw in (None, [], "event", 42):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    validate_event(raw)

    def test_wrong_content_type_is_rejected(self):
        event = {
            **self.minimal_event,
            "datacontenttype": "text/plain",
        }

        with self.assertRaises(ValidationError):
            validate_event(event)

    def test_wrong_specversion_is_rejected(self):
        event = {**self.minimal_event, "specversion": "2.0"}

        with self.assertRaises(ValidationError):
            validate_event(event)

    def test_input_is_not_mutated(self):
        original = dict(self.minimal_event)

        validate_event(original)

        self.assertEqual(original, self.minimal_event)


if __name__ == "__main__":
    unittest.main()