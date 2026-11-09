import logging
import os
import time
from typing import Any

import boto3
import botocore.exceptions
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from tqdm import tqdm

from utils.backupcommon import BackupSummary, local_files

MAX_ATTEMPTS = 3
DEFAULT_STORAGE_CLASS = "INTELLIGENT_TIERING"  # what the existing objects in the bucket use
MULTIPART_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB

# Errors that retrying cannot fix: the bucket is missing or we are not allowed to write to it.
_FATAL_CODES = ("AccessDenied", "NoSuchBucket", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken")


class S3BackupError(Exception):
    """A problem with the bucket or credentials that makes continuing pointless."""


def make_client(profile: str | None = None, region: str | None = None) -> Any:
    """An S3 client using the standard AWS credential chain (or the named profile)."""
    return boto3.session.Session(profile_name=profile, region_name=region).client("s3")


class S3Backup:
    """Pushes the files in a local directory to ``s3://<bucket>/<prefix>/``.

    S3 only shows an object once it is complete, so a key that exists with the right size is a finished upload and
    re-runs can skip it. Large files use automatic multipart uploads.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        client: Any = None,
        storage_class: str = DEFAULT_STORAGE_CLASS,
        retry_delay: float = 2.0,
        chunk_size: int = MULTIPART_CHUNK_SIZE,
    ):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client if client is not None else make_client()
        self.storage_class = storage_class
        self.retry_delay = retry_delay
        self.transfer_config = TransferConfig(multipart_threshold=chunk_size, multipart_chunksize=chunk_size)

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}"

    def _remote_sizes(self) -> dict[str, int]:
        """Map of file name to size for the objects directly under the prefix."""
        sizes: dict[str, int] = {}
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix + "/")
        for page in pages:
            for obj in page.get("Contents", []):
                name = obj["Key"][len(self.prefix) + 1 :]
                if name and "/" not in name:  # skip the folder marker and anything nested deeper
                    sizes[name] = obj["Size"]
        return sizes

    def _upload_file(self, local_path: str) -> None:
        name = os.path.basename(local_path)
        local_size = os.path.getsize(local_path)
        with tqdm(total=local_size, unit="B", unit_scale=True, desc=name[:40], disable=None) as bar:
            self.client.upload_file(
                local_path,
                self.bucket,
                self._key(name),
                ExtraArgs={"StorageClass": self.storage_class},
                Config=self.transfer_config,
                Callback=bar.update,
            )
        remote_size = self.client.head_object(Bucket=self.bucket, Key=self._key(name))["ContentLength"]
        if remote_size != local_size:
            raise S3UploadFailedError(f"size mismatch for {name}: local {local_size}, remote {remote_size}")

    def upload_dir(self, local_dir: str, dry_run: bool = False) -> BackupSummary:
        """Upload every regular, non-hidden file in ``local_dir`` (not recursive).

        Raises S3BackupError for missing credentials, a missing bucket or denied access; the listing happens first,
        so those are normally reported before any upload starts.
        """
        summary = BackupSummary()
        names = local_files(local_dir)
        try:
            remote_sizes = self._remote_sizes()
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
            raise S3BackupError(f"cannot list s3://{self.bucket}/{self.prefix}/: {e}") from e

        for name in names:
            path = os.path.join(local_dir, name)
            if remote_sizes.get(name) == os.path.getsize(path):
                summary.skipped.append(name)
            elif dry_run:
                summary.would_upload.append(name)
            else:
                self._upload_with_retries(path, summary)
        return summary

    def _upload_with_retries(self, path: str, summary: BackupSummary) -> None:
        name = os.path.basename(path)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._upload_file(path)
                summary.uploaded.append(name)
                return
            except (
                botocore.exceptions.BotoCoreError,
                botocore.exceptions.ClientError,
                S3UploadFailedError,
                OSError,
            ) as e:
                if any(code in str(e) for code in _FATAL_CODES) or isinstance(
                    e, botocore.exceptions.NoCredentialsError
                ):
                    raise S3BackupError(f"upload of {name} to s3://{self.bucket}/ refused: {e}") from e
                logging.warning(f"upload of {name} failed (attempt {attempt}/{MAX_ATTEMPTS}): {e}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self.retry_delay)
        summary.failed.append(name)
