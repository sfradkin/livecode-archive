import logging
from datetime import UTC, datetime

from internetarchive import upload  # internetarchive

from utils.templater import Templater


class ArchiveOrgUpload:
    MEDIA_TYPE = "movies"
    SETLIST_MEDIA_TYPE = "texts"
    COLLECTION = "toplap"
    LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
    HTML_WRAPPER_PRE = '<span style="font-family:Roboto, Noto, sans-serif;font-size:15px;white-space:pre-wrap;">'
    HTML_WRAPPER_POST = "</span>"

    def __init__(self):
        # nothing to configure at this point in time
        pass

    def uploadFile(self, row_data: dict, templates: Templater) -> bool:

        description = self.HTML_WRAPPER_PRE + templates.getDescription(row_data) + self.HTML_WRAPPER_POST
        description = Templater.replaceLbForAO(description)
        # description = description.replace(" -- ", "<br /><br />")

        file_id = row_data["archive_id"]

        try:
            meta_data = dict(
                mediatype=self.MEDIA_TYPE,
                collection=self.COLLECTION,
                creator=row_data["artist_name"],
                date=row_data["performance_date"],
                description=description,
                licenseurl=self.LICENSE_URL,
                subject=row_data["tags"].split(","),
                title=templates.getTitle(row_data),
            )

            print(f"uploading file to archive.org: {row_data['files']}")
            logging.info(f"uploading file to archive.org: {row_data['files']}")

            results = upload(file_id, files=[row_data["files"]], metadata=meta_data, verbose=True)
            print(f"completed uploading file: {row_data['files']}, url: {results[0].url}")
            logging.info(f"completed uploading file: {row_data['files']}, url: {results[0].url}")
            return True
        except Exception as e:
            print(f"An error occurred: {e}")
            logging.debug(f"An error occurred: {e}")
            return False

    def uploadSetlist(self, file_path: str, archive_id: str, title: str) -> None:
        try:
            meta_data = dict(
                mediatype=self.SETLIST_MEDIA_TYPE,
                collection=self.COLLECTION,
                date=datetime.now(UTC).strftime("%Y-%m-%d"),
                description=title,
                licenseurl=self.LICENSE_URL,
                title=f"{title} - Set List",
            )

            print(f"uploading set list to archive.org: {file_path}")
            logging.info(f"uploading set list to archive.org: {file_path}")

            results = upload(archive_id, files=[file_path], metadata=meta_data, verbose=True)
            print(f"completed uploading set list: {file_path}, url: {results[0].url}")
            logging.info(f"completed uploading set list: {file_path}, url: {results[0].url}")
        except Exception as e:
            print(f"An error occurred uploading set list: {e}")
            logging.debug(f"An error occurred uploading set list: {e}")
