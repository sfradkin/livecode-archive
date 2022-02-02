import ffmpeg # pip install ffmpeg-python
import sys
import subprocess
import re
import string
import logging

from utils.configreader import ConfigReader
from utils.jsonloader import JsonLoader
from utils.templater import Templater
from utils.youtubeupload import YouTubeUpload
from utils.archiveorgupload import ArchiveOrgUpload

import requests
import os
from tqdm import tqdm
from unidecode import unidecode

def downloadFile(url: str, dir: str) -> str:
    CHUNK_SIZE = 1024 * 10240 # 10 MB
    temp_file = dir + (os.path.basename(url)).replace(":", "-")

    session = requests.Session()

    r = session.get(url, stream=True)
    r.raise_for_status()

    if r.ok:
        print(f"downloading {url} to {temp_file}")
        total_size_in_bytes= int(r.headers.get('content-length', 0))
        progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True)

        with open(temp_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    progress_bar.update(len(chunk))
                    f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
    else:  # HTTP status code 4XX/5XX
        print(f"Download failed: status code {r.status_code}\n{r.text}")

    return temp_file

def cleanupFile(filename: str):
    if os.path.isfile(filename):
        os.remove(filename)
        print(f"{filename} cleaned up")
    else:    ## Show an error ##
        print(f"Error: file not found: {filename}")

def mergeFiles(files):
    # this will simply merge the videos in the order the files are specified in the CSV
    # more complex actions such as trimming individual videos or the resulting video will be added later if needed
    # bitrate and codec details will be the same for all videos we are merging together, so we only look at the first video
    file_arr = []
    temp_base_dir = livecode_config[CONFIG_GLOBAL]['video_file_location']

    # download all the files in the array
    for file in files:
        local_file = downloadFile(file, temp_base_dir)

        if 0 == os.path.getsize(local_file):
            cleanupFile(local_file)
        else:
            file_arr.append(local_file)

    video_file_no_ext = file_arr[0][:-4]
    merged_video_file = video_file_no_ext + "-merged.flv"

    print("merging videos in order")

    audio_codec, video_codec, vid_br_str, aud_br_str = getVideoDetails(file_arr[0])

    ##### Directly use FFMPEG to concat files due to some odd error with moviepy
    list_temp_file = temp_base_dir + 'list.txt'

    with open(list_temp_file,'w') as f:
        for fp in file_arr:
            f.write(f'file {fp}\n')

    # run ffmpeg to concat videos 
    command = "ffmpeg -f concat -safe 0 -i " + list_temp_file + " -c copy " + merged_video_file
    subprocess.call(command, shell=True)

    print(f"completed merging files.  new file at {merged_video_file}")

    for file in file_arr:
        cleanupFile(file)
        print(f"cleaned up temp file: {file}")

    # clean up list.txt
    cleanupFile(list_temp_file)

    return merged_video_file

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

#####

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

logging.basicConfig(filename='archiver.log', encoding='utf-8', level=logging.DEBUG)

livecode_config = ConfigReader.getConfig(INI_FILE_LOCATION)

headers = {'accept': 'application/json', 'Authorization': 'Api-Key ' + livecode_config[CONFIG_GLOBAL]['muxy_auth_token']}
muxy_url = 'https://muxy.tidalcycles.org/streams/?event__id=' + livecode_config[CONFIG_GLOBAL]['muxy_event']

print("retrieving livestream event metadata")

stream_metadata = JsonLoader.loadJsonMetadata(livecode_config[CONFIG_GLOBAL]['file_or_url'], livecode_config[CONFIG_GLOBAL]['metadata_file'], muxy_url, headers)

#stream_metadata = JsonLoader.loadJsonMetadataFromUrl(muxy_url, headers)

number_of_slots = stream_metadata['count']
print (f"number of slots in livestream: {number_of_slots}")
results = stream_metadata['results']

# get some global values
templates = Templater(livecode_config[CONFIG_STREAM][VIDEO_TITLE_TEMPLATE_KEY], livecode_config[CONFIG_STREAM][VIDEO_DESCR_TEMPLATE_KEY])
youtube_upload = YouTubeUpload(livecode_config[CONFIG_YOUTUBE])
archiveorg_upload = ArchiveOrgUpload()

# for testing, short circuit processing so we are only testing upload for a couple of items
processed_normal = 0
processed_merge = 0

processed_normal_limit = 200
processed_merge_limit = 200

for result in results:
    print (f"processing stream: {result['url']}, {result['publisher_name']}")
    logging.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
    logging.info(f"processing stream: {result['url']}, {result['publisher_name']}")
    # check to see if this performance has videos
    result_recs = result['recordings']
    if len(result_recs) > 0:
        print ("more than 0 recording files")
        if len(result_recs) > 1:
            if processed_merge < processed_merge_limit:
                # if there's more than 1 video file for this performance then we need to merge them together
                
                print ("greater than 1 recording files, merging")

                merge_file = mergeFiles(result_recs)

                publisher_name = result['publisher_name'].lower().replace(" ", "-")
                punct_chars = re.escape(string.punctuation)
                publisher_name = re.sub(r'[' + punct_chars + ']', '-', publisher_name)
                publisher_name = unidecode(publisher_name)

                result_data = {
                    'archive_id' : livecode_config[CONFIG_STREAM][ARCHIVE_ID_PREFIX_KEY] + publisher_name,
                    'files' : merge_file,
                    'artist_name' : result['publisher_name'],
                    'user_desc' : result['description'],
                    'location' : result['location'],
                    'performance_date' : result['starts_at'][0:10],
                    'performance_time' : result['starts_at'][11:16],
                    'tags' : livecode_config[CONFIG_STREAM][DEFAULT_TAGS_KEY],
                    'file_size' : os.path.getsize(merge_file)              
                }

                if (livecode_config[CONFIG_GLOBAL]['skipYoutube'] != 'True'):
                    # invoke youtube upload
                    video_id = youtube_upload.uploadFile(result_data, templates)
                    if video_id is None:
                        print("failed to upload file")
                        logging.info("failed to upload file")
                    else:
                        print(f"added youtube video {video_id}")
                        logging.info(f"added youtube video {video_id}")

                else:
                    print("skipping youtube upload")

                # upload to archive.org
                if (livecode_config[CONFIG_GLOBAL]['skipArchiveOrg'] != 'True'):
                    # invoke archive.org upload
                    archiveorg_upload.uploadFile(result_data, templates)
                    print("completed archive.org upload")
                    logging.info("completed archive.org upload")
                else:
                    print("skipping archive.org upload")

                processed_merge += 1
                cleanupFile(merge_file)
            else:
                print("at the process merge files limit, skipping")
                pass
        else:
            if processed_normal < processed_normal_limit:
                # grab data required and put into a dictionary with known keys
                print ("exactly 1 recording file, archiving")

                local_file = downloadFile(result['recordings'][0], livecode_config[CONFIG_GLOBAL]['video_file_location'])

                publisher_name = result['publisher_name'].lower().replace(" ", "-")
                punct_chars = re.escape(string.punctuation)
                publisher_name = re.sub(r'[' + punct_chars + ']', '-', publisher_name)
                publisher_name = unidecode(publisher_name)

                result_data = {
                    'archive_id' : livecode_config[CONFIG_STREAM][ARCHIVE_ID_PREFIX_KEY] + publisher_name,
                    'files' : local_file,
                    'artist_name' : result['publisher_name'],
                    'user_desc' : result['description'],
                    'location' : result['location'],
                    'performance_date' : result['starts_at'][0:10],
                    'performance_time' : result['starts_at'][11:16],
                    'tags' : livecode_config[CONFIG_STREAM][DEFAULT_TAGS_KEY],
                    'file_size' : os.path.getsize(local_file)
                }

                if (livecode_config[CONFIG_GLOBAL]['skipYoutube'] != 'True'):
                    # invoke youtube upload
                    video_id = youtube_upload.uploadFile(result_data, templates)
                    if video_id is None:
                        print("failed to upload file")
                        logging.info("failed to upload file")
                    else:
                        print(f"added youtube video {video_id}")
                        logging.info(f"added youtube video {video_id}")

                else:
                    print("skipping youtube upload")

                # upload to archive.org
                if (livecode_config[CONFIG_GLOBAL]['skipArchiveOrg'] != 'True'):
                    # invoke archive.org upload
                    archiveorg_upload.uploadFile(result_data, templates)
                    print("completed archive.org upload")
                    logging.info("completed archive.org upload")
                else:
                    print("skipping archive.org upload")
                
                processed_normal += 1
                cleanupFile(local_file)
            else:
                print("at the process normal files limit, skipping")
                pass
    else:
        print(f"skipping processing for performance {result['publisher_name']} due to no video files")

    logging.info("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
