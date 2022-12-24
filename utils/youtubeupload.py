import http.client
import logging
import random
import time

import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from tqdm import tqdm

from utils.templater import Templater


class YouTubeUpload:

    # Explicitly tell the underlying HTTP transport library not to retry, since
    # we are handling retry logic ourselves.
    httplib2.RETRIES = 1

    # Maximum number of times to retry before giving up.
    MAX_RETRIES = 10

    # Always retry when these exceptions are raised.
    RETRIABLE_EXCEPTIONS = (
        httplib2.HttpLib2Error,
        IOError,
        http.client.NotConnected,
        http.client.IncompleteRead,
        http.client.ImproperConnectionState,
        http.client.CannotSendRequest,
        http.client.CannotSendHeader,
        http.client.ResponseNotReady,
        http.client.BadStatusLine,
    )

    # Always retry when an apiclient.errors.HttpError with one of these status
    # codes is raised.
    RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

    CHUNK_SIZE = 1024 * 1024 * 50

    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    MUSIC = 10
    PRIVATE = "private"
    LICENSE = "creativeCommon"

    def __init__(self, youtube_config):

        newCreds = Credentials(
            "",
            refresh_token=youtube_config["refresh_token"],
            token_uri=youtube_config["token_uri"],
            client_id=youtube_config["client_id"],
            client_secret=youtube_config["client_secret"],
        )

        self.google_service = build(self.YOUTUBE_API_SERVICE_NAME, self.YOUTUBE_API_VERSION, credentials=newCreds)

    #### From the Google YouTube API examples: https://github.com/youtube/api-samples/blob/master/python/upload_video.py
    # This method implements an exponential backoff strategy to resume a
    # failed upload.
    def resumable_upload(self, request, filesize):
        response = None
        error = None
        retry = 0
        prev_bytes = 0
        progress_bar = tqdm(total=filesize, unit="iB", unit_scale=True)
        while response is None:
            try:
                status, response = request.next_chunk()
                if response is not None:
                    cur_chunk = filesize - prev_bytes
                    progress_bar.update(cur_chunk)
                    prev_bytes = filesize
                    progress_bar.close()

                    if "id" in response:
                        print(f"Video id {response['id']} was successfully uploaded.")
                        logging.info(f"Video id {response['id']} was successfully uploaded.")
                        return response
                    else:
                        print(f"The upload failed with an unexpected response: {response}")
                        logging.info(f"The upload failed with an unexpected response: {response}")
                else:
                    cur_chunk = status.resumable_progress - prev_bytes
                    progress_bar.update(cur_chunk)
                    prev_bytes = status.resumable_progress

            except HttpError as e:
                if e.resp.status in self.RETRIABLE_STATUS_CODES:
                    error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status, e.content)
                else:
                    print(f"error uploading, code: {e.resp.status}, text: {e.content}")
                    logging.debug(f"error uploading, code: {e.resp.status}, text: {e.content}")
                    break

            except self.RETRIABLE_EXCEPTIONS as e:
                error = "A retriable error occurred: %s" % e

            if error is not None:
                print(error)
                retry += 1
                if retry > self.MAX_RETRIES:
                    print("No longer attempting to retry.")
                    break

                max_sleep = 2**retry
                sleep_seconds = random.random() * max_sleep
                print(f"Sleeping {sleep_seconds} seconds and then retrying...")
                time.sleep(sleep_seconds)

    def uploadFile(self, row_data: dict, templates: Templater) -> str:
        desc = templates.getDescription(row_data)
        desc = Templater.replaceLbForYT(desc)

        body = dict(
            snippet=dict(
                title=templates.getTitle(row_data),
                description=desc,
                tags=row_data["tags"].split(","),
                categoryId=self.MUSIC,
            ),
            status=dict(privacyStatus=self.PRIVATE, licence=self.LICENSE),
            recordingDetails=dict(recordingDate=row_data["performance_date"]),
        )

        # Call the API's videos.insert method to create and upload the video.
        insert_request = self.google_service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=MediaFileUpload(row_data["files"], chunksize=self.CHUNK_SIZE, resumable=True),
        )

        print(f"uploading: {row_data['files']}")
        logging.info(f"uploading: {row_data['files']}")

        response = self.resumable_upload(insert_request, row_data["file_size"])
        if response is not None:
            print(response)
            logging.info(response)
            return response["id"]
        else:
            print("failed to upload file")
            logging.info("failed to upload file")
            return None
