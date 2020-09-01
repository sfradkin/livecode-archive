from internetarchive import upload # pip install internetarchive

from moviepy.editor import VideoFileClip # pip install moviepy

import ffmpeg # pip install ffmpeg-python
import sys

from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

import configparser

config = configparser.ConfigParser()
config.read('live-code-uploader.ini')
youtube_config = config['youtube.upload']

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

newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                 token_uri=youtube_config['token_uri'], 
                                                 client_id=youtube_config['client_id'], 
                                                 client_secret=youtube_config['client_secret'])

google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=newCreds)

body=dict(
    snippet=dict(
      title='Test of automated upload',
      description='This is just a test',
      tags=["automated, uploaded"],
      categoryId=10 # music 
    ),
    status=dict(
      privacyStatus="private",
      licence="creativeCommon"
    ),
    recordingDetails=dict(
        recordingDate="2020-08-01"
    )
  )

# Call the API's videos.insert method to create and upload the video.
insert_request = google_service.videos().insert(
    part=",".join(body.keys()),
    body=body,
    media_body=MediaFileUpload(edited_video_file)
)

response = insert_request.execute()

print(response)
