from internetarchive import upload # internetarchive

from utils.templater import Templater

import logging

class ArchiveOrgUpload:

    MEDIA_TYPE = "movies"
    COLLECTION = "toplap"
    LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
    HTML_WRAPPER_PRE = '<span style="font-family:Roboto, Noto, sans-serif;font-size:15px;white-space:pre-wrap;">'
    HTML_WRAPPER_POST = '</span>'
    
    def __init__(self):
        # nothing to configure at this point in time
        pass
   
    def uploadFile(self, row_data: dict, templates: Templater) -> str:

        description = self.HTML_WRAPPER_PRE + templates.getDescription(row_data) + self.HTML_WRAPPER_POST
        description = Templater.replaceLbForAO(description)
       # description = description.replace(" -- ", "<br /><br />")

        file_id = row_data['archive_id']
        
        try:
            meta_data = dict(mediatype=self.MEDIA_TYPE, collection=self.COLLECTION, creator=row_data['artist_name'], date=row_data['performance_date'],
                            description=description,
                            licenseurl=self.LICENSE_URL, subject=row_data['tags'].split(","), title=templates.getTitle(row_data))

            print(f"uploading file to archive.org: {row_data['files']}")
            logging.info(f"uploading file to archive.org: {row_data['files']}")

            results = upload(file_id, files=[row_data['files']], metadata=meta_data, verbose=True)
            print(f"completed uploading file: {row_data['files']}, url: {results[0].url}")
            logging.info(f"completed uploading file: {row_data['files']}, url: {results[0].url}")
        except Exception as e:
            print(f'An error occurred: {e}')
            logging.debug(f'An error occurred: {e}')
            pass