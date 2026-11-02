
#!/usr/bin/env python3

"""Create an Opsfeed API key and store its hash in SSM Parameter Store."""

import argparse
import hashlib
import json
import secrets
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError


DEFAULT_PARAMETER_NAME = "/opsfeed/dev/tenant-api-keys"
DEFAULT_REGION = "us-east-1"


def generate_api_key() -> str:
    """Generate a high-entropy API key."""
    secret = secrets.token_urlsafe(32)
    return f"opsfeed_live_{secret}"


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 hexadecimal digest of an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


from botocore.exceptions import ClientError

def load_tenant_map(ssm, parameter_name: str) -> dict[str, str]:
    try:
        response = ssm.get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ParameterNotFound":
            return {}
        raise

    value = response["Parameter"]["Value"]
    tenant_map = json.loads(value)

    if not isinstance(tenant_map, dict):
        raise ValueError("The SSM tenant map must be a JSON object.")

    return tenant_map
    

def store_tenant_map(
    ssm,
    parameter_name: str,
    tenant_map: dict[str, str],
) -> None:
    """Write the updated tenant map as an encrypted SSM SecureString."""
    ssm.put_parameter(
        Name=parameter_name,
        Description="Opsfeed API-key SHA-256 hashes mapped to tenant IDs",
        Type="SecureString",
        Value=json.dumps(tenant_map, separators=(",", ":")),
        Overwrite=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Opsfeed API key for an existing tenant."
    )
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Tenant ID to associate with this API key.",
    )
    parser.add_argument(
        "--parameter-name",
        default=DEFAULT_PARAMETER_NAME,
        help=f"SSM parameter name (default: {DEFAULT_PARAMETER_NAME}).",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION}).",
    )

    args = parser.parse_args()

    if not args.tenant_id.strip():
        parser.error("--tenant-id cannot be empty.")

    ssm = boto3.client("ssm", region_name=args.region)

    # Generate the raw key and its lookup hash.
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    try:
        tenant_map = load_tenant_map(ssm, args.parameter_name)

        # Store only the hash, never the raw API key.
        tenant_map[key_hash] = args.tenant_id

        store_tenant_map(
            ssm,
            args.parameter_name,
            tenant_map,
        )

    except (BotoCoreError, ClientError, ValueError) as exc:
        print(f"Could not create API key: {exc}", file=sys.stderr)
        return 1

    # Display the raw key only after SSM confirms the write succeeded.
    print("\nAPI key created successfully.")
    print(f"Tenant ID: {args.tenant_id}")
    print(f"SSM parameter: {args.parameter_name}")
    print("\nCopy this key now. It will not be displayed again:\n")
    print(api_key)
    print("\nTreat this value like a password.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
