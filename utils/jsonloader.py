import json

import requests


class JsonLoader:
    @classmethod
    def loadJsonMetadata(cls, file_or_url: str, file_loc: str, url: str, headers: dict) -> dict:

        json_data = {}

        if "file" == file_or_url:
            json_data = cls.loadJsonMetadataFromFile(file_loc)
        else:
            json_data = cls.loadJsonMetadataFromUrl(url, headers)

        return json_data

    @classmethod
    def loadJsonMetadataFromFile(cls, file_loc: str) -> dict:

        with open(file_loc, "r") as json_file:
            data = json_file.read()

        # parse file
        return json.loads(data)

    @classmethod
    def loadJsonMetadataFromUrl(cls, url: str, headers: dict) -> dict:
        r = requests.get(url, headers=headers)
        print(f"returned from get: {r}")
        return r.json()
