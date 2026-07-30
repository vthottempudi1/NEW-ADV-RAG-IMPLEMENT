from __future__ import annotations

from typing import Any

from botocore.exceptions import NoCredentialsError

from app.config import settings
from app.storage.storage_backend import StorageBackend


class S3Storage(StorageBackend):
    """StorageBackend implementation backed by an S3 bucket.

    Reads/writes objects through a boto3 S3 client, resolving credentials from
    explicit settings (access key/secret/session token), a named AWS profile,
    or the default boto3 credential chain, in that order.
    """

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ):
        """Configure the target bucket/region and construct (or accept) a boto3 S3 client.

        `bucket`/`region` default to `settings.s3_cache_bucket`/`settings.aws_region` when
        not given. Raises RuntimeError if no bucket can be resolved. If `client` is passed,
        it is used as-is (useful for tests/mocking) and no boto3 session is created;
        otherwise a boto3 session is built from configured AWS credentials or profile.
        """
        self.bucket = bucket or settings.s3_cache_bucket
        self.region = region or settings.aws_region

        if not self.bucket:
            raise RuntimeError("S3 cache bucket is required")

        if client is not None:
            self.client = client
            return

        import boto3

        session_kwargs: dict[str, str] = {}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            if settings.aws_session_token:
                session_kwargs["aws_session_token"] = settings.aws_session_token
        elif settings.aws_profile:
            session_kwargs["profile_name"] = settings.aws_profile

        session = boto3.Session(**session_kwargs)
        self.client = session.client("s3", region_name=self.region)

    def exists(self, key: str) -> bool:
        """Return True if an object with this key exists in the bucket, False otherwise (including on any error)."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def save_bytes(self, key: str, data: bytes) -> None:
        """Upload `data` to the bucket under `key`, raising RuntimeError with a setup hint if AWS credentials are missing."""
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc

    def read_bytes(self, key: str) -> bytes:
        """Download and return the full contents of the object at `key`, raising RuntimeError with a setup hint if AWS credentials are missing."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc
        return response["Body"].read()

    def url_for(self, key: str) -> str:
        """Return the `s3://bucket/key` URI for the given key (does not verify the object exists)."""
        return f"s3://{self.bucket}/{key}"
