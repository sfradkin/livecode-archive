from internetarchive import upload # pip install internetarchive

from moviepy.editor import VideoFileClip # pip install moviepy

import ffmpeg # pip install ffmpeg-python
import sys

# from apiclient.discovery import build
# from apiclient.errors import HttpError
# from apiclient.http import MediaFileUpload
# from oauth2client.client import flow_from_clientsecrets
# from oauth2client.file import Storage
# from oauth2client.tools import argparser, run_flow

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

import configparser

config = configparser.ConfigParser()
config.read('live-code-uploader.ini')
youtube_config = config['youtube.upload']

# from google.oauth2 import service_account
# import googleapiclient.discovery


#google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file


# pip install google-api-python-client
# pip install google-auth-oauthlib google-auth-httplib2

CLIENT_SECRETS_FILE = youtube_config['youtube.client.secrets']

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
YOUTUBE_UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/youtube","https://www.googleapis.com/auth/youtubepartner","https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube.force-ssl"]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# test video is already saved locally, so we don't overwrite it at this point in time

video_file = youtube_config['test.file']
video_file_no_ext = video_file[:-4]
edited_video_file = video_file_no_ext + "-edited.flv"
edit_type = 1
trim_front_time = "00:03:15"
trim_end_time = "00:27:10"

print("processing video: {}".format(video_file))

# use ffprobe to get the bitrate of the stream
# flv files don't seem to respond with a separate bitrate for the audio and video streams, so we just grab the overall bitrate
try:
    probe = ffmpeg.probe(video_file)
except ffmpeg.Error as e:
    print(e.stderr, file=sys.stderr)
    sys.exit(1)

# overall bitrate can be found in probe['format']['bit_rate']
# we also find the audio and video codecs used.  this is most likely going to be 'h264' and 'aac' for flv files, but we want to
# be sure

video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)

overall_bitrate = int(probe['format']['bit_rate'])
video_codec = video_stream['codec_name']
audio_codec = audio_stream['codec_name']
audio_bitrate = 0
video_bitrate = 0

# now do some minimal calculation to generate an audio and video bitrate to use when re-encoding the file after clipping
if overall_bitrate < 1000000:
    audio_bitrate = 128000
else:
    audio_bitrate = 256000

video_bitrate = overall_bitrate - audio_bitrate

# moviepy wants the bitrates as strings like '128k', etc... so now we convert the integer bitrates into that string
vid_br_str = str(video_bitrate)[:-3] + 'k'
aud_br_str = str(audio_bitrate)[:-3] + 'k'

print("things about the video: o_br: {}, aud_br: {}, vid_br: {}, aud_cod: {}, vid_cod: {}, vid_br_str: {}, aud_br_str: {}"
    .format(overall_bitrate, audio_bitrate, video_bitrate, audio_codec, video_codec, vid_br_str, aud_br_str))

# clip = VideoFileClip(video_file).subclip(trim_front_time, trim_end_time)  #3:15 - 27:10

# clip.write_videofile(edited_video_file, codec=video_codec, audio_codec=audio_codec, audio_bitrate=aud_br_str, bitrate=vid_br_str)

# clip.close()

VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, YOUTUBE_UPLOAD_SCOPES)
credentials = flow.run_console()


# SCOPES = ['https://www.googleapis.com/auth/sqlservice.admin']
# SERVICE_ACCOUNT_FILE = '/path/to/service.json'

# credentials = service_account.Credentials.from_service_account_file(CLIENT_SECRETS_FILE, scopes=YOUTUBE_UPLOAD_SCOPES)
# google_service = googleapiclient.discovery.build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)
# response = sqladmin.instances().list(project='exemplary-example-123').execute()


google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


# flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
#     scope=YOUTUBE_UPLOAD_SCOPE,
#     message="missing secrets")

# credentials = run_flow(flow, storage, args)

# google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, http=credentials.authorize(httplib2.Http()))

body=dict(
    snippet=dict(
      title='Test of automated upload',
      description='This is just a test',
      tags=["automated, uploaded"],
      categoryId=10
    ),
    status=dict(
      privacyStatus="private"
    )
  )

# Call the API's videos.insert method to create and upload the video.
insert_request = google_service.videos().insert(
    #onBehalfOfContentOwner="true",
    #onBehalfOfContentOwnerChannel="UC_N48pxd05dX53_8vov8zqA",
    part=",".join(body.keys()),
    body=body,
    # The chunksize parameter specifies the size of each chunk of data, in
    # bytes, that will be uploaded at a time. Set a higher value for
    # reliable connections as fewer chunks lead to faster uploads. Set a lower
    # value for better recovery on less reliable connections.
    #
    # Setting "chunksize" equal to -1 in the code below means that the entire
    # file will be uploaded in a single HTTP request. (If the upload fails,
    # it will still be retried where it left off.) This is usually a best
    # practice, but if you're using Python older than 2.6 or if you're
    # running on App Engine, you should set the chunksize to something like
    # 1024 * 1024 (1 megabyte).
    media_body=MediaFileUpload(edited_video_file)
)

response = insert_request.execute()

print(response)
