"""Back up the files in a local directory to an FTP host over FTPS.

Usage: uv run backup-to-ftp.py <local_dir> <subdirectory> [--host HOST] [--base-dir DIR] [--file-mode 644]
       [--dir-mode 755] [--dry-run]

Files go to <base-dir>/<subdirectory> on the server; the base directory defaults to "public_html/live coding".

You are prompted for the FTP username and password; nothing is stored. Files already on the server with the same
size are skipped, so it is safe to re-run after an interruption.
"""

import argparse
import getpass
import ssl
import sys

from utils.backupcommon import clean_subdirectory
from utils.ftpbackup import DEFAULT_DIR_MODE, DEFAULT_FILE_MODE, FtpBackup

# The FTP server's TLS certificate (Let's Encrypt) is issued for the hosting server's own hostname, not for
# ftp.fradkin.com, although both resolve to the same address. Verification only passes against this name.
DEFAULT_HOST = "sh-cp16.lax2.servername.online"
DEFAULT_BASE_DIR = "public_html/live coding"


def remote_path(base_dir: str, subdirectory: str) -> str:
    """Join the base dir and the subdirectory, refusing a subdirectory that is empty or would leave the base dir."""
    return base_dir.rstrip("/") + "/" + clean_subdirectory(subdirectory)


def main(argv: list[str] | None = None, tls: bool = True) -> int:
    # tls is only ever False in tests that talk to a plain local server; there is no command-line way to disable it
    parser = argparse.ArgumentParser(description="Back up a local directory to an FTP host over FTPS.")
    parser.add_argument("local_dir", help="directory containing the files to upload")
    parser.add_argument("subdirectory", help="subdirectory of the base directory to upload into, e.g. my-stream-2026")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"FTP host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=21, help="FTP port (default: 21)")
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        help=f"remote base directory, relative to the FTP login directory (default: {DEFAULT_BASE_DIR})",
    )
    parser.add_argument(
        "--file-mode",
        type=lambda s: int(s, 8),
        default=DEFAULT_FILE_MODE,
        help=f"octal permissions for uploaded files (default: {DEFAULT_FILE_MODE:o})",
    )
    parser.add_argument(
        "--dir-mode",
        type=lambda s: int(s, 8),
        default=DEFAULT_DIR_MODE,
        help=f"octal permissions for directories this script creates (default: {DEFAULT_DIR_MODE:o})",
    )
    parser.add_argument("--dry-run", action="store_true", help="list what would be uploaded without uploading")
    args = parser.parse_args(argv)

    try:
        remote_dir = remote_path(args.base_dir, args.subdirectory)
    except ValueError as e:
        parser.error(str(e))

    username = input("FTP username: ")
    password = getpass.getpass("FTP password: ")

    backup = FtpBackup(
        args.host,
        username,
        password,
        remote_dir,
        port=args.port,
        tls=tls,
        file_mode=args.file_mode,
        dir_mode=args.dir_mode,
    )

    try:
        summary = backup.upload_dir(args.local_dir, dry_run=args.dry_run)
    except ssl.SSLCertVerificationError as e:
        print(f"TLS certificate verification failed for {args.host}: {e}", file=sys.stderr)
        print(
            "Not falling back to an unverified or plain connection. If the certificate is issued for a different "
            "hostname that points at the same server, pass that name with --host.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(f"dry run: {len(summary.would_upload)} to upload, {len(summary.skipped)} already present")
        for name in summary.would_upload:
            print(f"  would upload: {name}")
        return 0

    print(f"uploaded {len(summary.uploaded)}, skipped {len(summary.skipped)}, failed {len(summary.failed)}")
    for name in summary.failed:
        print(f"  FAILED: {name}", file=sys.stderr)
    for name in summary.chmod_failed:
        print(f"  PERMISSIONS NOT SET: {name} (server rejected SITE CHMOD)", file=sys.stderr)
    return 1 if summary.failed or summary.chmod_failed else 0


if __name__ == "__main__":
    sys.exit(main())
