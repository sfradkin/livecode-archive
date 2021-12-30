# import configparser
import csv
#import re
from googleapiclient.discovery import build, Resource # google-api-python-client
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials # google-auth-oauthlib
#from string import Template
from internetarchive import upload # internetarchive
from moviepy.editor import VideoFileClip, concatenate_videoclips # pip install moviepy
import ffmpeg # pip install ffmpeg-python
import sys
import subprocess

from utils.configreader import ConfigReader
from utils.jsonloader import JsonLoader
from utils.templater import Templater
from utils.youtubeupload import YouTubeUpload

import requests

expectedFields = ['archiveid','fileedit','times','files','artistname','userdesc','location','performancedate','performancetime','algorave','tech','tags']

INI_FILE_LOCATION = 'live-code-uploader.ini'
CONFIG_GLOBAL = 'global.props'
CONFIG_YOUTUBE = 'youtube.upload'
CONFIG_ARCHIVE_ORG = 'archive.org.upload'
CONFIG_STREAM = 'stream.props'
STREAM_PROPS_JSON_LOC = 'json_location'
VIDEO_TITLE_TEMPLATE_KEY = 'video_title_template'
VIDEO_DESCR_TEMPLATE_KEY = 'video_description_template'
ARCHIVE_ID_PREFIX_KEY = 'archive_id_prefix'
DEFAULT_TAGS_KEY = 'default_tags'

# a rewrite and reconfiguration of how this works
# based off the new streaming system
# it now generates a large json file that has a bunch of metadata that can be used to drive
# a lot of what i previously put into a csv file
# this json file will be used to drive archiving now
# an override system will need to be in place to allow for video edits
# assumptions: json file is pulled down from the api and is local (entries are in reverse order), all videos are also downloaded and are local

# read the json file
# iterate over the file in reverse order as the entries are in reverse time order
# for now, assume there are no overrides
# look at the list of video files for each entry
# if there is one file, then we can just upload it directly to youtube and archive.org
# if there is more than one file, then merge them together
# however, the filenames need to be put into order (timestamps are in the filename) because they aren't necessarily in order.

livecode_config = ConfigReader.getConfig(INI_FILE_LOCATION)

#stream_metadata = JsonLoader.loadJsonMetadata(str(livecode_config[CONFIG_STREAM][STREAM_PROPS_JSON_LOC]))

headers = {'accept': 'application/json', 'Authorization': 'Api-Key ' + livecode_config[CONFIG_GLOBAL]['muxy_auth_token']}
muxy_url = 'https://muxy.tidalcycles.org/streams/?event__id=' + livecode_config[CONFIG_GLOBAL]['muxy_event']

print("retrieving livestream event metadata")

stream_metadata = JsonLoader.loadJsonMetadataFromUrl(muxy_url, headers)

number_of_slots = stream_metadata['count']
print (f"number of slots in livestream: {number_of_slots}")
results = stream_metadata['results']

# get some global values
templates = Templater(livecode_config[CONFIG_STREAM][VIDEO_TITLE_TEMPLATE_KEY], livecode_config[CONFIG_STREAM][VIDEO_DESCR_TEMPLATE_KEY])
#youtube_upload = YouTubeUpload(livecode_config[CONFIG_YOUTUBE])
#need to create the archiveorg module
#archiveorg_upload = ArchiveOrgUpload(livecode_config[CONFIG_ARCHIVE_ORG])

for result in results:
    print (f"processing stream: {result['url']}, {result['publisher_name']}")
    # check to see if this performance has videos
    result_recs = result['recordings']
    if len(result_recs) > 0:
        print ("more than 0 recording files")
        if len(result_recs) > 1:
            # if there's more than 1 video file for this performance then we need to merge them together
            print ("greater than 1 recording files, passing for now")
            pass
        else:
            # grab data required and put into a dictionary with known keys
            print ("exactly 1 recording file, archiving")
            result_data = {
                'archive_id' : livecode_config[CONFIG_STREAM][ARCHIVE_ID_PREFIX_KEY] + result['publisher_name'].lower().replace(" ", "-"),
                'files' : result['recordings'][0],
                'artist_name' : result['publisher_name'],
                'user_desc' : result['description'],
                'location' : result['location'],
                'performance_date' : result['starts_at'][0:10],
                'performance_time' : result['starts_at'][11:16],
                'tags' : livecode_config[CONFIG_STREAM][DEFAULT_TAGS_KEY]                
            }

            if (livecode_config[CONFIG_GLOBAL]['skipYoutube'] != 'True'):
                # invoke youtube upload
                video_id = youtube_upload.uploadFile(result_data)
                print (f"added youtube video {video_id}")
            else:
                print("skipping youtube upload")

            # upload to archive.org
            if (livecode_config[CONFIG_GLOBAL]['skipArchiveOrg'] != 'True'):
                # invoke archive.org upload
                archiveorg_upload.uploadFile(result_data)
            else:
                print("skipping archive.org upload")     
    else:
        print(f"skipping processing for performance {result['publisher_name']} due to no video files")


##################################################################################################################



# read config in csv
def readCsv(configLoc):
    csv_rows = []
    with open(configLoc, mode='r') as csv_file:
        csv_reader = csv.reader(csv_file)
        csv_rows = []
        for row in csv_reader:
            csv_rows.append(row)
    return csv_rows

# parses a video file, outputs some details, returns info required to re-encode the final video
def getVideoDetails(videoPath):
    # use ffprobe to get the bitrate of the stream
    # flv files don't seem to respond with a separate bitrate for the audio and video streams, so we just grab the overall bitrate
    try:
        probe = ffmpeg.probe(videoPath)
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

    print(f"things about the video: overall_bitrate: {overall_bitrate}, audio_bitrate: {audio_bitrate}, video_bitrate: {video_bitrate}, audio_codec: {audio_codec}, ")
    print(f"video_codec: {video_codec}, vid_br_str: {vid_br_str}, aud_br_str: {aud_br_str}")

    return audio_codec, video_codec, vid_br_str, aud_br_str

# edit video if needed and return the path to the new file
def editFile(editType, videoPath, times):
    if editType == 'none':
        return videoPath
    elif editType == 'trim':
        video_file_no_ext = videoPath[:-4]
        edited_video_file = video_file_no_ext + "-edited.flv"
        times_arr = times.split(",")
        trim_front_time = times_arr[0]
        trim_end_time = times_arr[1]

        print(f"processing video: {videoPath}, editType: {editType}, trimming at: {trim_front_time} and {trim_end_time}")

        audio_codec, video_codec, vid_br_str, aud_br_str = getVideoDetails(videoPath)

        clip = VideoFileClip(videoPath).subclip(trim_front_time, trim_end_time)

        clip.write_videofile(edited_video_file, codec=video_codec, audio_codec=audio_codec, audio_bitrate=aud_br_str, bitrate=vid_br_str)

        clip.close()

        print(f"completed trimming file.  new file at {edited_video_file}")

        return edited_video_file
    elif editType == 'merge':
        # this will simply merge the videos in the order the files are specified in the CSV
        # more complex actions such as trimming individual videos or the resulting video will be added later if needed
        # bitrate and codec details will be the same for all videos we are merging together, so we only look at the first video

        # get an array of files, videoPath in this case should be a list of files
        file_arr = videoPath.split(",")

        video_file_no_ext = file_arr[0][:-4]
        merged_video_file = video_file_no_ext + "-merged.flv"

        print(f"processing videos: {videoPath}, editType: {editType}, merging videos in order")

        audio_codec, video_codec, vid_br_str, aud_br_str = getVideoDetails(file_arr[0])

        ##### Directly use FFMPEG to concat files due to some odd error with moviepy

        with open('list.txt','w') as f:
            for fp in file_arr:
                f.write(f'file {fp}\n')

        # run ffmpeg to concat videos 
        command = "ffmpeg -f concat -safe 0 -i list.txt -c copy " + merged_video_file
        subprocess.call(command, shell=True)

        print(f"completed merging files.  new file at {merged_video_file}")

        return merged_video_file
    else:
        pass

def uploadToYoutube(youtube_config, file_path, row_data, templates):
    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    MUSIC = 10
    PRIVATE = "private"
    LICENSE = "creativeCommon"
    
    newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                    token_uri=youtube_config['token_uri'], 
                                                    client_id=youtube_config['client_id'], 
                                                    client_secret=youtube_config['client_secret'])

    google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=newCreds)

    desc = templateReplaceDesc(templates, row_data)
    desc = desc.replace(" -- ", chr(13) + chr(10) + chr(13) + chr(10))

    body=dict(
        snippet=dict(
            title=templateReplaceTitle(templates, row_data),
            description=desc,
            tags=row_data['tags'].split(","),
            categoryId=MUSIC
        ),
        status=dict(
            privacyStatus=PRIVATE,
            licence=LICENSE
        ),
        recordingDetails=dict(
            recordingDate=row_data['performance_date']
        )
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = google_service.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(file_path)
    )

    print(f"uploading: {file_path}")

    response = insert_request.execute()

    print(response)
    return response['id']

def uploadToArchiveOrg(archive_org_config, file_path, row_data, templates, archivePrefix):
    MEDIA_TYPE = "movies"
    COLLECTION = "toplap"
    LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
    HTML_WRAPPER_PRE = '<span style="font-family:Roboto, Noto, sans-serif;font-size:15px;white-space:pre-wrap;">'
    HTML_WRAPPER_POST = '</span>'

    description = HTML_WRAPPER_PRE + templateReplaceDesc(templates, row_data) + HTML_WRAPPER_POST
    description = description.replace(" -- ", "<br /><br />")

    file_id = archivePrefix + row_data['archive_id']
    
    try:
        meta_data = dict(mediatype=MEDIA_TYPE, collection=COLLECTION, creator=row_data['artist_name'], date=row_data['performance_date'],
                         description=description,
                         licenseurl=LICENSE_URL, subject=row_data['tags'].split(","), title=templateReplaceTitle(templates, row_data))

        print(f'uploading file: {file_id}')

        result = upload(file_id, files=[file_path], metadata=meta_data, verbose=True)

        print(f'completed uploading file: {file_id}')
    except Exception as e:
        print(f'An error occurred: {e}')
        pass

def createYoutubePlaylist(youtube_config, playlist_title, playlist_description):
    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    
    newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                    token_uri=youtube_config['token_uri'], 
                                                    client_id=youtube_config['client_id'], 
                                                    client_secret=youtube_config['client_secret'])

    google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=newCreds)

    desc = playlist_description.replace(" -- ", chr(13) + chr(10) + chr(13) + chr(10))

    body=dict(
        snippet=dict(
            title=playlist_title,
            description=desc
        ),
        status=dict(
            privacyStatus="private"
        )
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = google_service.playlists().insert(
        part=",".join(body.keys()),
        body=body
    )

    print(f"inserting playlist")

    response = insert_request.execute()

    print(response)
    return response['id']

def addToPlaylist(youtube_config, playlist_id, video_id):
    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    
    newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                    token_uri=youtube_config['token_uri'], 
                                                    client_id=youtube_config['client_id'], 
                                                    client_secret=youtube_config['client_secret'])

    google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=newCreds)

    body=dict(
        snippet=dict(
            playlist_id=playlist_id,
            resource_id=dict (
                kind="youtube#video",
                videoId=video_id
            )
        )
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = google_service.playlistItems().insert(
        part=",".join(body.keys()),
        body=body
    )

    print(f"inserting video: {video_id} into playlist: {playlist_id}")

    response = insert_request.execute()

    print(response)

# youtube_config, archive_org_config, global_config = readProps()

# csv_rows = readCsv(global_config['csv.location'])
# # the first row is specific configuration for archiving, all subsequent rows are the actual performance data
# titleTemplate = csv_rows[0][0]
# descriptionTemplate = csv_rows[0][1]
# templates = {'title':titleTemplate, 'description':descriptionTemplate}
# archivePrefix = csv_rows[0][2]
# playlist_title = csv_rows[0][3]
# playlist_description = csv_rows[0][4]

# playlist_id = ""
# video_id = ""

# titleTemplateFields = extractKeys(titleTemplate)
# descriptionTemplateFields = extractKeys(descriptionTemplate)

# print(f'title fields: {titleTemplateFields}, description fields: {descriptionTemplateFields}')

# # create playlist
# if (global_config['skipPlaylist'] != 'True'):
#     playlist_id = createYoutubePlaylist(youtube_config, playlist_title, playlist_description)
# else:
#     print("skipping youtube playlist creation")

# # loop through the rows
# for row in csv_rows[1:]:
#     # now do everything...
#     row_data = {
#         'archive_id' : row[0],
#         'file_edit' : row[1],
#         'times' : row[2],
#         'files' : row[3],
#         'artist_name' : row[4],
#         'user_desc' : row[5],
#         'location' : row[6],
#         'performance_date' : row[7],
#         'performance_time' : row[8],
#         'algorave' : row[9],
#         'tech' : row[10],
#         'tags' : row[11]
#     }

#     # edit file and save
#     new_path = editFile(row_data['file_edit'], row_data['files'], row_data['times'])

#     # upload to youtube
#     if (global_config['skipYoutube'] != 'True'):
#         video_id = uploadToYoutube(youtube_config, new_path, row_data, templates)
#     else:
#         print("skipping youtube upload")

#     # add video to playlist
#     if (global_config['skipPlaylist'] != 'True'):
#         addToPlaylist(youtube_config, playlist_id, video_id)
#     else:
#         print("skipping adding video to playlist")

#     # upload to archive.org
#     if (global_config['skipArchiveOrg'] != 'True'):
#         uploadToArchiveOrg(archive_org_config, new_path, row_data, templates, archivePrefix)
#     else:
#         print("skipping archive.org upload")
