# Live Coding Archiver

This is a Python script that manages the archiving of live streams managed by muxy to archive.org
and the Eulerroom channel on YouTube.

This script reads the metadata from muxy, downloads video files for each performer, concatenates
videos together if needed, then re-uploads to both archive.org and YouTube with tags.

## Pre-Requisites

Please contact the maintainer for information on setting up authentication correctly.

Python 3.X is required.

`pip install -r requirements.txt`

Copy the `live-code-uploader-template.ini` file to `live-code-uploader.ini` and fill out the required values.

Install the `pre-commit` tool:

`pip install pre-commit`

Verify with:

`pre-commit --version`

Now install locally:

`pre-commit install`

You can now test it by running:

`pre-commit run --all-files`

It will run prior to any commit now.


## Usage

`python ./live-coding-archiver.py`

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
    playlist_title_template= Not currently used
    playlist_description_template= Not currently used

## Other

If you need to regenerate the `requirements.txt` or `requirements-dev.txt` files for any reason use `pip-tools`.

`pip-compile --upgrade -o requirements.txt pyproject.toml`

`pip-compile --upgrade --extra dev -o requirements-dev.txt pyproject.toml`
