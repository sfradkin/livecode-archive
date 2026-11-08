# Live Coding Archiver

This is a Python script that manages the archiving of live streams managed by muxy to archive.org
and the Eulerroom channel on YouTube.

This script reads the metadata from muxy, downloads video files for each performer, concatenates
videos together if needed, then re-uploads to both archive.org and YouTube with tags.

## Pre-Requisites

Please contact the maintainer for information on setting up authentication correctly.

This project uses [uv](https://docs.astral.sh/uv/) to manage Python and dependencies. Install it, then from the
repo root run:

`uv sync`

This installs the Python version pinned in `.python-version` (if needed) and all dependencies, including the dev group.
Python 3.12 or newer is required.

Copy the `live-code-uploader-template.ini` file to `live-code-uploader.ini` and fill out the required values.

The `pre-commit` tool is installed as part of the dev group. Install the git hook locally:

`uv run pre-commit install`

You can now test it by running:

`uv run pre-commit run --all-files`

It will run prior to any commit now.


## Usage

`uv run live-coding-archiver.py`

Some messages will output to the console, other debug information will output to the `archiver.log` file.

### Properties explanation

There are a number of properties to fill out in the `live-code-uploader.ini` file.

    [global.props]
    skipYoutube= This can be `True` to skip archiving to YouTube or `False` to archive
    skipArchiveOrg= This can be `True` to skip archiving to archive.org or `False` to archive
    skipPlaylist= Always `True` for now
    video_file_location= Set to an absolute location on your local disk to use as a prefix for where to store downloaded video files temporarily
    muxy_auth_token= Authentication token for accessing muxy
    muxy_event= The event number for the stream to be archived
    file_or_url= If set to `file` will look for a local metadata file, if set to `url` will access the muxy server url
    metadata_file= Location of a local metatdata file
    video_file_or_url= If `file` will look for all video files on local disk based on location listed in metadata, if `url` will download video files from url listed in metadata

    [archive.org.upload]
    none= Leave blank, unused

    [youtube.upload]
    refresh_token= Contact maintainer for information
    token_uri= Contact maintainer for information
    client_id= Contact maintainer for information
    client_secret= Contact maintainer for information

    [stream.props]
    default_tags= The default tags to tag videos with
    video_title_template= This is a template that gets filled in and used as the title for videos
    video_description_template= This is a template that gets filled in and used as the description for videos
    archive_id_prefix= A unique string that is pre-pended to the archive.org video identifier
    stream_title= The title of the stream, used as the heading of the generated set list
    playlist_title_template= Not currently used
    playlist_description_template= Not currently used

## Other

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

- Add a dependency: `uv add <package>` (or `uv add --dev <package>` for dev tools)
- Upgrade everything: `uv lock --upgrade && uv sync`
- Run the checks CI runs: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, `uv run pytest`

## Set list

After all performances are archived, the archiver generates a plain-text set list (the `stream_title`, then every
set in chronological order with its UTC start time, artist, title, description and archive.org URL; sets with no
recording are marked) and uploads it to its own archive.org item, `<archive_id_prefix>setlist`. It is skipped when `skipArchiveOrg=True`.

To preview the set list for any metadata file without archiving anything:

`uv run generate-setlist.py around-the-world.json --title "Around the World"`

Add `--archive-id-prefix <prefix>` to include predicted archive.org URLs (assumes every set with recordings is uploaded under that
prefix). In a real run the archiver only links sets whose archive.org upload succeeded.

The output goes to `setlists/<metadata-name>-setlist.txt`, or use `--output PATH`. `setlists/` and `*-setlist.txt` are
gitignored so test set lists are never committed.

## Backups

### FTP

Push a directory of recordings to an FTP host over FTPS (TLS, with certificate verification; it never falls back to
plain FTP):

`uv run backup-to-ftp.py ~/Downloads/nov-2026-stream/recordings`

You are prompted for the FTP username and password; nothing is stored. By default it uploads to `ftp.fradkin.com`,
into `public-html/live coding/around-the-world-nov-2026` (relative to the FTP login directory). Override with `--host`,
`--port` and `--remote-dir`.

- `--dry-run` lists what would be uploaded without uploading or creating directories.
- Files are uploaded as `<name>.part` and renamed once complete, and files already on the server with the same size
  are skipped, so it is safe to re-run after an interruption. A dropped connection is retried up to 3 times per file.
- Uploaded files are set to `644` and directories the script creates to `755` using `SITE CHMOD` (override with
  `--file-mode` / `--dir-mode`, octal). Files skipped as already present are chmod-ed too, so a re-run repairs
  permissions from an earlier run. Files under `public-html` with these modes can be served by the web server.
- The exit code is non-zero if any file failed or its permissions could not be set. A server that does not support
  `SITE CHMOD` fails right away, before anything is uploaded.
