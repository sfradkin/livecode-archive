import json
import requests

class JsonLoader:
    
    @classmethod
    def loadJsonMetadata(cls, file_loc: str) -> dict:

        with open(file_loc, 'r') as json_file:
            data=json_file.read()

        # parse file
        return json.loads(data)

    @classmethod
    def loadJsonMetadataFromUrl(cls, url: str, headers: dict) -> dict:
        r = requests.get(url, headers=headers)
        print (f"returned from get: {r}")
        return r.json()
