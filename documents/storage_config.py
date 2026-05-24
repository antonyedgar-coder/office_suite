"""DigitalOcean Spaces / S3 storage options for client documents."""

from __future__ import annotations

import os


def spaces_env_config() -> dict[str, str]:
    """Read and normalize Spaces env vars (raises KeyError if required vars missing)."""
    endpoint = (os.environ["DO_SPACES_ENDPOINT"] or "").strip().rstrip("/")
    region = (os.getenv("DO_SPACES_REGION") or "").strip()
    if not region and endpoint:
        # e.g. https://blr1.digitaloceanspaces.com -> blr1
        host = endpoint.replace("https://", "").replace("http://", "")
        region = host.split(".")[0] if host else ""
    return {
        "access_key": os.environ["DO_SPACES_KEY"].strip(),
        "secret_key": os.environ["DO_SPACES_SECRET"].strip(),
        "bucket_name": os.environ["DO_SPACES_BUCKET"].strip(),
        "endpoint_url": endpoint,
        "region_name": region or "us-east-1",
    }


def spaces_storage_options() -> dict:
    """django-storages S3Storage OPTIONS tuned for DigitalOcean Spaces."""
    cfg = spaces_env_config()
    return {
        "access_key": cfg["access_key"],
        "secret_key": cfg["secret_key"],
        "bucket_name": cfg["bucket_name"],
        "endpoint_url": cfg["endpoint_url"],
        "region_name": cfg["region_name"],
        "signature_version": "s3v4",
        "addressing_style": "virtual",
        "default_acl": "private",
        "file_overwrite": False,
        "querystring_auth": True,
        "object_parameters": {"CacheControl": "private, max-age=3600"},
    }
