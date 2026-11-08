"""Generate a set list text file from a metadata JSON file, for testing.

Usage: uv run generate-setlist.py <metadata.json> --title "Stream Title" [--output PATH]

By default the file is written to setlists/<metadata-stem>-setlist.txt, which is gitignored.
"""

import argparse
import os

from utils.jsonloader import JsonLoader
from utils.setlist import predict_archive_ids, write_setlist

DEFAULT_OUTPUT_DIR = "setlists"


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description="Generate a set list text file from a metadata JSON file.")
    parser.add_argument("metadata_file", help="path to the metadata JSON file")
    parser.add_argument("--title", required=True, help="stream title to put at the top of the set list")
    parser.add_argument("--output", help=f"output path (default: {DEFAULT_OUTPUT_DIR}/<metadata-stem>-setlist.txt)")
    parser.add_argument(
        "--archive-id-prefix",
        help="include predicted archive.org URLs, assuming every set with recordings was uploaded under this prefix",
    )
    args = parser.parse_args(argv)

    output = args.output
    if output is None:
        stem = os.path.splitext(os.path.basename(args.metadata_file))[0]
        output = os.path.join(DEFAULT_OUTPUT_DIR, f"{stem}-setlist.txt")

    metadata = JsonLoader.loadJsonMetadataFromFile(args.metadata_file)
    archive_ids = predict_archive_ids(metadata["results"], args.archive_id_prefix) if args.archive_id_prefix else None
    path = write_setlist(args.title, metadata["results"], output, archive_ids)
    print(f"wrote set list for {len(metadata['results'])} sets to {path}")
    return path


if __name__ == "__main__":
    main()
