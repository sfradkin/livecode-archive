"""Back up the files in a local directory to an S3 bucket.

Usage: uv run backup-to-s3.py <local_dir> <subdirectory> [--bucket BUCKET] [--profile PROFILE] [--region REGION]
       [--storage-class CLASS] [--dry-run]

Files go to s3://<bucket>/<subdirectory>/<file>, the same folder names used on the FTP host. Credentials come from the
standard AWS sources (environment variables or ~/.aws, optionally a named --profile); nothing is prompted or stored.
Files already in the bucket with the same size are skipped, so it is safe to re-run after an interruption.
"""

import argparse
import sys

from utils.backupcommon import clean_subdirectory
from utils.s3backup import DEFAULT_STORAGE_CLASS, S3Backup, S3BackupError, make_client

DEFAULT_BUCKET = "live-coding-42406474-571c-402b-a18c-3d42d1e32c9a"


def main(argv: list[str] | None = None, client=None) -> int:
    parser = argparse.ArgumentParser(description="Back up a local directory to an S3 bucket.")
    parser.add_argument("local_dir", help="directory containing the files to upload")
    parser.add_argument("subdirectory", help="folder in the bucket to upload into, e.g. my-stream-2026")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help=f"S3 bucket (default: {DEFAULT_BUCKET})")
    parser.add_argument("--profile", help="AWS profile to use (default: the standard credential chain)")
    parser.add_argument("--region", help="AWS region (default: from the profile or environment)")
    parser.add_argument(
        "--storage-class",
        default=DEFAULT_STORAGE_CLASS,
        help=f"S3 storage class for uploaded objects (default: {DEFAULT_STORAGE_CLASS})",
    )
    parser.add_argument("--dry-run", action="store_true", help="list what would be uploaded without uploading")
    args = parser.parse_args(argv)

    try:
        prefix = clean_subdirectory(args.subdirectory)
    except ValueError as e:
        parser.error(str(e))

    backup = S3Backup(
        args.bucket,
        prefix,
        client=client if client is not None else make_client(args.profile, args.region),
        storage_class=args.storage_class,
    )

    try:
        summary = backup.upload_dir(args.local_dir, dry_run=args.dry_run)
    except S3BackupError as e:
        print(f"S3 backup stopped: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"dry run: {len(summary.would_upload)} to upload, {len(summary.skipped)} already present")
        for name in summary.would_upload:
            print(f"  would upload: {name}")
        return 0

    print(f"uploaded {len(summary.uploaded)}, skipped {len(summary.skipped)}, failed {len(summary.failed)}")
    for name in summary.failed:
        print(f"  FAILED: {name}", file=sys.stderr)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
