import logging
import os
import shutil

import requests
from tqdm import tqdm

from utils.configreader import ConfigReader
from utils.jsonloader import JsonLoader

# to download all the files, be sure to set the 'video_file_location' property


def downloadFile(file_or_url: str, url: str, dir: str) -> str:
    CHUNK_SIZE = 1024 * 10240  # 10 MB
    temp_file = dir + (os.path.basename(url)).replace(":", "-")

    if file_or_url == "file":
        logging.debug(f"local file mode: copying {url} to {temp_file}")
        shutil.copy2(url, temp_file)
    else:
        logging.debug("url mode")
        session = requests.Session()

        r = session.get(url, stream=True)
        r.raise_for_status()

        if r.ok:
            print(f"downloading {url} to {temp_file}")
            total_size_in_bytes = int(r.headers.get("content-length", 0))
            progress_bar = tqdm(total=total_size_in_bytes, unit="iB", unit_scale=True)

            with open(temp_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        progress_bar.update(len(chunk))
                        f.write(chunk)
                        f.flush()
                        os.fsync(f.fileno())
        else:  # HTTP status code 4XX/5XX
            print(f"Download failed: status code {r.status_code}\n{r.text}")

    return temp_file


INI_FILE_LOCATION = "live-code-uploader.ini"
CONFIG_GLOBAL = "global.props"
CONFIG_YOUTUBE = "youtube.upload"
CONFIG_ARCHIVE_ORG = "archive.org.upload"
CONFIG_STREAM = "stream.props"
STREAM_PROPS_JSON_LOC = "json_location"
VIDEO_TITLE_TEMPLATE_KEY = "video_title_template"
VIDEO_DESCR_TEMPLATE_KEY = "video_description_template"
ARCHIVE_ID_PREFIX_KEY = "archive_id_prefix"
DEFAULT_TAGS_KEY = "default_tags"

logging.basicConfig(filename="download-all.log", encoding="utf-8", level=logging.DEBUG)

livecode_config = ConfigReader.getConfig(INI_FILE_LOCATION)

headers = {
    "accept": "application/json",
    "Authorization": "Api-Key " + livecode_config[CONFIG_GLOBAL]["muxy_auth_token"],
}
muxy_url = "https://muxy.tidalcycles.org/streams/?event__id=" + livecode_config[CONFIG_GLOBAL]["muxy_event"]

print("retrieving livestream event metadata")

stream_metadata = JsonLoader.loadJsonMetadata(
    livecode_config[CONFIG_GLOBAL]["file_or_url"], livecode_config[CONFIG_GLOBAL]["metadata_file"], muxy_url, headers
)

number_of_slots = stream_metadata["count"]
print(f"number of slots in livestream: {number_of_slots}")
results = stream_metadata["results"]

for result in results:
    print(f"processing stream: {result['url']}, {result['publisher_name']}")
    logging.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
    logging.info(f"processing stream: {result['url']}, {result['publisher_name']}")
    # check to see if this performance has videos
    result_recs = result["recordings"]
    if len(result_recs) > 0:
        print("more than 0 recording files")
        if len(result_recs) > 1:
            file_arr = []
            temp_base_dir = livecode_config[CONFIG_GLOBAL]["video_file_location"]

            # download all the files in the array
            for file in result_recs:
                local_file = downloadFile(livecode_config[CONFIG_GLOBAL]["video_file_or_url"], file, temp_base_dir)
        else:
            print("exactly 1 recording file, archiving")

            local_file = downloadFile(
                livecode_config[CONFIG_GLOBAL]["video_file_or_url"],
                result["recordings"][0],
                livecode_config[CONFIG_GLOBAL]["video_file_location"],
            )

print("completed downloading all files")
