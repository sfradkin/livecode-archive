from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from templater import Templater

class YouTubeUpload:

    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    MUSIC = 10
    PRIVATE = "private"
    LICENSE = "creativeCommon"

    def __init__(self, youtube_config):
        
        newCreds = Credentials('', refresh_token=youtube_config['refresh_token'], 
                                                        token_uri=youtube_config['token_uri'], 
                                                        client_id=youtube_config['client_id'], 
                                                        client_secret=youtube_config['client_secret'])

        self.google_service = build(self.YOUTUBE_API_SERVICE_NAME, self.YOUTUBE_API_VERSION, credentials=newCreds)
    
    def uploadFile(self, row_data: dict, templates: Templater) -> str:
        desc = templates.getDescription(row_data)
        desc = Templater.replaceLbForYT(desc)

        body=dict(
            snippet=dict(
                title=templates.getTitle(row_data),
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
