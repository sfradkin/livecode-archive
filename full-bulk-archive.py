import configparser
import csv
import re
from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from string import Template
from internetarchive import upload

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

# edit video if needed and return the path to the new file
def editFile(editType, videoPath, times):
    if editType == 'none':
        return videoPath
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
    LICENSE = "creativeCommons"
    
    newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                    token_uri=youtube_config['token_uri'], 
                                                    client_id=youtube_config['client_id'], 
                                                    client_secret=youtube_config['client_secret'])

    google_service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=newCreds)

    desc = templateReplaceDesc(templates, row_data)
    desc = desc.replace("--", chr(10) + chr(13)),

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
    description = description.replace("--", "<br />")

    file_id = archivePrefix + row_data['archive_id']
    
    try:
        meta_data = dict(mediatype=MEDIA_TYPE, collection=COLLECTION, creator=row_data['artist_name'], date=row_data['performance_date'],
                         description=description,
                         licenseurl=LICENSE_URL, subject=row_data['tags'].split(","), title=templateReplaceTitle(templates, row_data))

        print('uploading file: ' + file_id)

        result = upload(file_id, files=[file_path], metadata=meta_data, verbose=True)

        print('completed uploading file: ' + file_id)
    except Exception as e:
        print(f'An error occurred: {e}')
        pass

youtube_config, archive_org_config, global_config = readProps()

csv_rows = readCsv(global_config['csv.location'])
# the first row is specific configuration for archiving, all subsequent rows are the actual performance data
titleTemplate = csv_rows[0][0]
descriptionTemplate = csv_rows[0][1]
templates = {'title':titleTemplate, 'description':descriptionTemplate}
archivePrefix = csv_rows[0][2]

titleTemplateFields = extractKeys(titleTemplate)
descriptionTemplateFields = extractKeys(descriptionTemplate)

print(f'title fields: {titleTemplateFields}, description fields: {descriptionTemplateFields}')

# create playlist
#playlist_id = createPlaylist()

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
    #addToPlaylist(playlist_id, video_id)

    # upload to archive.org
    if (global_config['skipArchiveOrg'] != 'True'):
        uploadToArchiveOrg(archive_org_config, new_path, row_data, templates, archivePrefix)
    else:
        print("skipping archive.org upload")
