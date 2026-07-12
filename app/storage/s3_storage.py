from __future__ import annotations

from typing import Any

from botocore.exceptions import NoCredentialsError

from app.config import settings
from app.storage.storage_backend import StorageBackend


# Learner Note: S3 storage is part of the storage abstraction layer.
class S3Storage(StorageBackend):
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent s3 storage within the storage abstraction layer.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
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

    # Learner note: Encapsulates exists so this responsibility can be understood, tested, and changed independently.
    def exists(self, key: str) -> bool:
        """Perform exists for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    # Learner note: Persists save bytes consistently so state changes remain controlled and testable.
    def save_bytes(self, key: str, data: bytes) -> None:
        """Perform save bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc

    # Learner note: Retrieves read bytes in one place so callers share consistent access behavior.
    def read_bytes(self, key: str) -> bytes:
        """Perform read bytes for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found for S3 storage. "
                "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env or configure AWS_PROFILE."
            ) from exc
        return response["Body"].read()

    # Learner note: Encapsulates url for so this responsibility can be understood, tested, and changed independently.
    def url_for(self, key: str) -> str:
        """Perform url for for the storage abstraction layer.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return f"s3://{self.bucket}/{key}"
