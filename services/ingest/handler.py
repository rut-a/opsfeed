
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

try:
    # When imported locally as services.ingest.handler
    from .validation import ValidationError, validate_event
except ImportError:
    # When Lambda loads handler.py as the top-level "handler" module
    from validation import ValidationError, validate_event
    

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_BODY_BYTES = 64 * 1024
CACHE_TTL_SECONDS = 300
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/cloudevents+json",
}

_tenant_map_cache = None
_ssm = None
_table = None


def _problem(status, title, detail, errors=None, extra_headers=None):
    """Build a consistent RFC 9457-style error response."""
    problem = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if errors is not None:
        problem["errors"] = errors

    headers = {"content-type": "application/problem+json"}
    if extra_headers:
        headers.update(extra_headers)

    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(problem),
    }


def _success(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _get_ssm():
    """Create the SSM client only when it is first needed."""
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _get_table():
    """Create the DynamoDB table resource only when needed."""
    global _table
    if _table is None:
        table_name = os.environ["LOGS_TABLE_NAME"]
        _table = boto3.resource("dynamodb").Table(table_name)
    return _table


def _reject_nonfinite(value):
    """Reject JSON NaN and Infinity, which are not standard JSON values."""
    raise ValueError(f"non-standard JSON number: {value}")


def _load_tenant_map():
    """Return the cached API-key-hash-to-tenant mapping."""
    global _tenant_map_cache

    now = time.monotonic()
    if (
        _tenant_map_cache is not None
        and now < _tenant_map_cache["expires_at"]
    ):
        return _tenant_map_cache["mapping"]

    parameter_name = os.environ["TENANT_MAP_PARAMETER"]
    response = _get_ssm().get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )

    mapping = json.loads(
        response["Parameter"]["Value"],
        parse_float=Decimal,
        parse_constant=_reject_nonfinite,
    )

    if not isinstance(mapping, dict) or not all(
        isinstance(key, str)
        and re.fullmatch(r"[0-9a-f]{64}", key)
        and isinstance(tenant, str)
        and tenant.strip()
        for key, tenant in mapping.items()
    ):
        raise ValueError("tenant map has an invalid structure")

    _tenant_map_cache = {
        "mapping": mapping,
        "expires_at": now + CACHE_TTL_SECONDS,
    }
    return mapping


def _authenticate(headers):
    """Return the tenant ID, or None when the supplied key is invalid."""
    authorization = headers.get("authorization", "")
    match = re.fullmatch(r"Bearer\s+(\S+)", authorization, re.IGNORECASE)

    if match is None:
        return None

    api_key = match.group(1)
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    mapping = _load_tenant_map()
    return mapping.get(key_hash)


def _decode_body(request):
    """Decode the API Gateway body and enforce the byte limit."""
    body = request.get("body")
    if not isinstance(body, str):
        raise ValueError("request body must be a string")

    if request.get("isBase64Encoded", False):
        try:
            raw_bytes = base64.b64decode(body, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("request body has invalid base64 encoding") from exc
    else:
        raw_bytes = body.encode("utf-8")

    if len(raw_bytes) > MAX_BODY_BYTES:
        raise OverflowError("request body exceeds 64 KB")

    return raw_bytes.decode("utf-8")


def _build_item(event, tenant_id):
    """Convert a normalized event into the DynamoDB item layout."""
    event_time = datetime.fromisoformat(
        event["time"].replace("Z", "+00:00")
    )
    received_at = datetime.now(timezone.utc)
    retention_days = int(os.environ.get("RETENTION_DAYS", "30"))

    if retention_days < 1:
        raise ValueError("RETENTION_DAYS must be at least 1")

    item = {
        "pk": f"{tenant_id}#{event_time:%Y-%m-%d}",
        "sk": f"{event['time']}#{event['id']}",
        "tenant_id": tenant_id,
        "id": event["id"],
        "source": event["source"],
        "type": event["type"],
        "time": event["time"],
        "severity": event["severity"],
        "received_at": received_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "expires_at": int(
            (received_at + timedelta(days=retention_days)).timestamp()
        ),
    }

    if "subject" in event:
        item["service"] = event["subject"]

    if "correlationid" in event:
        item["correlation_id"] = event["correlationid"]

    if "data" in event:
        item["data"] = event["data"]

    return item


def handler(request, context):
    """API Gateway HTTP API Lambda entry point."""
    # Normalize header names because HTTP header names are case-insensitive.
    headers = {
        str(key).lower(): str(value)
        for key, value in (request.get("headers") or {}).items()
    }

    # Authentication must happen before parsing or storing the event.
    try:
        tenant_id = _authenticate(headers)
    except Exception:
        logger.exception("tenant_lookup_failed")
        return _problem(
            503,
            "Service Unavailable",
            "Authentication service is temporarily unavailable.",
            extra_headers={"retry-after": "5"},
        )

    if tenant_id is None:
        return _problem(
            401,
            "Unauthorized",
            "A valid bearer API key is required.",
            extra_headers={"www-authenticate": "Bearer"},
        )

    content_type = headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_CONTENT_TYPES:
        return _problem(
            415,
            "Unsupported Media Type",
            "Content-Type must be application/json or "
            "application/cloudevents+json.",
        )

    try:
        body = _decode_body(request)
    except OverflowError:
        return _problem(
            413,
            "Content Too Large",
            "Request body must not exceed 64 KB.",
        )
    except (ValueError, UnicodeDecodeError):
        return _problem(
            400,
            "Bad Request",
            "Request body must be valid UTF-8 text or valid base64-encoded UTF-8.",
        )

    try:
        raw_event = json.loads(
            body,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, ValueError):
        return _problem(
            400,
            "Bad Request",
            "Request body must contain valid JSON.",
        )

    try:
        event = validate_event(raw_event)
    except ValidationError as exc:
        return _problem(
            400,
            "Event Validation Failed",
            "One or more event fields are invalid.",
            errors=exc.errors,
        )

    try:
        item = _build_item(event, tenant_id)
        _get_table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")

        if error_code == "ConditionalCheckFailedException":
            logger.info(
                "event_duplicate tenant_id=%s event_id=%s",
                tenant_id,
                event["id"],
            )
            return _success(
                200,
                {"status": "duplicate", "id": event["id"]},
            )

        logger.exception(
            "event_storage_failed tenant_id=%s event_id=%s",
            tenant_id,
            event["id"],
        )
        return _problem(
            500,
            "Internal Server Error",
            "The event could not be stored.",
        )
    except Exception:
        logger.exception(
            "event_storage_failed tenant_id=%s event_id=%s",
            tenant_id,
            event["id"],
        )
        return _problem(
            500,
            "Internal Server Error",
            "The event could not be stored.",
        )

    logger.info(
        "event_created tenant_id=%s event_id=%s",
        tenant_id,
        event["id"],
    )
    return _success(
        201,
        {"status": "created", "id": event["id"]},
    )
