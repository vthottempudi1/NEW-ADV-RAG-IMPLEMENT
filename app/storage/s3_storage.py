from __future__ import annotations

from typing import Any

from botocore.exceptions import NoCredentialsError

from app.config import settings
from app.storage.storage_backend import StorageBackend


class S3Storage(StorageBackend):
    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ):
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
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def save_bytes(self, key: str, data: bytes) -> None:
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc

    def read_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc
        return response["Body"].read()

    def url_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"
