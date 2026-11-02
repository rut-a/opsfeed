import re
from datetime import datetime, timezone
from typing import Any


ALLOWED_FIELDS = {
    "specversion",
    "id",
    "source",
    "type",
    "time",
    "subject",
    "severity",
    "correlationid",
    "datacontenttype",
    "data",
}

ALLOWED_SEVERITIES = {"info", "warning", "error", "critical"}

# At least two dot-separated segments.
# Each segment starts with a lowercase letter.
TYPE_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
)

# RFC 3339-style timestamp with mandatory timezone.
# Fractional seconds are optional and may contain more than 6 digits.
TIME_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(\d+))?"
    r"(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


class ValidationError(ValueError):
    """Raised when an event fails validation."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors

        details = "; ".join(
            f"{error['field']}: {error['message']}"
            for error in errors
        )

        super().__init__(details)


def _normalise_time(value: Any) -> str:
    """Validate a timestamp and return fixed-width UTC format."""

    if not isinstance(value, str):
        raise ValueError(
            f"must be a timestamp string; received {value!r}"
        )

    match = TIME_PATTERN.fullmatch(value)

    if match is None:
        raise ValueError(
            "must be an RFC 3339 timestamp with a timezone, "
            "for example '2026-10-28T10:30:00+02:00'; "
            f"received {value!r}"
        )

    date_time, fraction, offset = match.groups()

    # Python datetime supports microseconds: exactly 6 digits.
    fraction = (fraction or "")[:6].ljust(6, "0")

    normalized = f"{date_time}.{fraction}{offset}"

    if offset == "Z":
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "contains an invalid calendar date, time, or offset; "
            f"received {value!r}"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "must include an explicit timezone; "
            f"received {value!r}"
        )

    utc_time = parsed.astimezone(timezone.utc)

    return utc_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_event(raw: Any) -> dict[str, Any]:
    """Validate an event and return a normalized copy."""

    if not isinstance(raw, dict):
        raise ValidationError([
            {
                "field": "$",
                "message": (
                    "event body must be a JSON object; "
                    f"received {type(raw).__name__}"
                ),
            }
        ])

    errors: list[dict[str, str]] = []

    def add_error(field: str, message: str) -> None:
        errors.append({"field": field, "message": message})

    # Reject tenant identity supplied by the producer and
    # any attribute outside the contract.
    for field in raw:
        if field == "tenant_id":
            add_error(
                field,
                "is forbidden; tenant identity must not be "
                "supplied in the event body",
            )
        elif field not in ALLOWED_FIELDS:
            add_error(
                field,
                "is not an allowed attribute; allowed fields are "
                f"{', '.join(sorted(ALLOWED_FIELDS))}",
            )

    # Required string fields.
    required_strings = ("specversion", "id", "source", "type", "time")

    for field in required_strings:
        if field not in raw:
            add_error(field, "is required")
        elif not isinstance(raw[field], str) or not raw[field].strip():
            add_error(
                field,
                "must be a non-empty string; "
                f"received {raw[field]!r}",
            )

    # Supported contract version.
    if isinstance(raw.get("specversion"), str):
        if raw["specversion"] != "1.0":
            add_error(
                "specversion",
                "must be '1.0'; "
                f"received {raw['specversion']!r}",
            )

    # Event type syntax.
    event_type = raw.get("type")

    if isinstance(event_type, str) and event_type.strip():
        if not TYPE_PATTERN.fullmatch(event_type):
            add_error(
                "type",
                "must be a dotted lowercase identifier with at least "
                "two segments, for example 'com.opsfeed.deploy.finished'; "
                f"received {event_type!r}",
            )

    # Normalize the timestamp, if it is present and non-empty.
    normalized_time = None

    if isinstance(raw.get("time"), str) and raw["time"].strip():
        try:
            normalized_time = _normalise_time(raw["time"])
        except ValueError as exc:
            add_error("time", str(exc))

    # Optional string attributes.
    for field in ("subject", "correlationid"):
        if field in raw:
            value = raw[field]

            if not isinstance(value, str) or not value.strip():
                add_error(
                    field,
                    "must be a non-empty string when provided; "
                    f"received {value!r}",
                )

    # Severity defaults to info.
    severity = raw.get("severity", "info")

    if (
        not isinstance(severity, str)
        or severity not in ALLOWED_SEVERITIES
    ):
        add_error(
            "severity",
            "must be one of "
            f"{', '.join(sorted(ALLOWED_SEVERITIES))}; "
            f"received {severity!r}",
        )

    # Only JSON content is accepted by this contract.
    if "datacontenttype" in raw:
        content_type = raw["datacontenttype"]

        if content_type != "application/json":
            add_error(
                "datacontenttype",
                "must be 'application/json'; "
                f"received {content_type!r}",
            )

    # A JSON object is represented by a Python dict.
    if "data" in raw and not isinstance(raw["data"], dict):
        add_error(
            "data",
            "must be a JSON object; "
            f"received {type(raw['data']).__name__}",
        )

    # Report all accumulated problems together.
    if errors:
        raise ValidationError(errors)

    # Return a new dictionary; do not modify the caller's input.
    result = dict(raw)
    result["severity"] = severity
    result["time"] = normalized_time

    return result