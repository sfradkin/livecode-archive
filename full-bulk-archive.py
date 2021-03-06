import configparser
import csv
import re
from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from string import Template
from internetarchive import upload
from moviepy.editor import VideoFileClip, concatenate_videoclips # pip install moviepy
import ffmpeg # pip install ffmpeg-python
import sys
import subprocess

expectedFields = ['archiveid','fileedit','times','files','artistname','userdesc','location','performancedate','performancetime','algorave','tech','tags']

# read props
def readProps():
    config = configparser.ConfigParser()
    config.read('live-code-uploader.ini')
    g_config = config['global.props']
    yt_config = config['youtube.upload']
    archive_config = config['archive.org.upload']

    return yt_config, archive_config, g_config

# read config in csv
def readCsv(configLoc):
    csv_rows = []
    with open(configLoc, mode='r') as csv_file:
        csv_reader = csv.reader(csv_file)
        csv_rows = []
        for row in csv_reader:
            csv_rows.append(row)
    return csv_rows

# extract the keys from the template so we know what to substitute
def extractKeys(templateStr):
    expr = re.compile(r"\$\w+")
    return expr.findall(templateStr)

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

def templateReplaceTitle(templates, values):
    return templateReplace(templates['title'], values)

def templateReplaceDesc(templates, values):
    return templateReplace(templates['description'], values)

def templateReplace(templateStr, values):
    t = Template(templateStr)
    return t.substitute(values)

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

youtube_config, archive_org_config, global_config = readProps()

csv_rows = readCsv(global_config['csv.location'])
# the first row is specific configuration for archiving, all subsequent rows are the actual performance data
titleTemplate = csv_rows[0][0]
descriptionTemplate = csv_rows[0][1]
templates = {'title':titleTemplate, 'description':descriptionTemplate}
archivePrefix = csv_rows[0][2]
playlist_title = csv_rows[0][3]
playlist_description = csv_rows[0][4]

playlist_id = ""
video_id = ""

titleTemplateFields = extractKeys(titleTemplate)
descriptionTemplateFields = extractKeys(descriptionTemplate)

print(f'title fields: {titleTemplateFields}, description fields: {descriptionTemplateFields}')

# create playlist
if (global_config['skipPlaylist'] != 'True'):
    playlist_id = createYoutubePlaylist(youtube_config, playlist_title, playlist_description)
else:
    print("skipping youtube playlist creation")

# loop through the rows
for row in csv_rows[1:]:
    # now do everything...
    row_data = {
        'archive_id' : row[0],
        'file_edit' : row[1],
        'times' : row[2],
        'files' : row[3],
        'artist_name' : row[4],
        'user_desc' : row[5],
        'location' : row[6],
        'performance_date' : row[7],
        'performance_time' : row[8],
        'algorave' : row[9],
        'tech' : row[10],
        'tags' : row[11]
    }

    # edit file and save
    new_path = editFile(row_data['file_edit'], row_data['files'], row_data['times'])

    # upload to youtube
    if (global_config['skipYoutube'] != 'True'):
        video_id = uploadToYoutube(youtube_config, new_path, row_data, templates)
    else:
        print("skipping youtube upload")

    # add video to playlist
    if (global_config['skipPlaylist'] != 'True'):
        addToPlaylist(youtube_config, playlist_id, video_id)
    else:
        print("skipping adding video to playlist")

    # upload to archive.org
    if (global_config['skipArchiveOrg'] != 'True'):
        uploadToArchiveOrg(archive_org_config, new_path, row_data, templates, archivePrefix)
    else:
        print("skipping archive.org upload")
