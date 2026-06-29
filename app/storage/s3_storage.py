from __future__ import annotations

from typing import Any

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

        self.client = boto3.client("s3", region_name=self.region)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def save_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def read_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def url_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"