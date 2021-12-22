import json

class JsonLoader:
    
    @classmethod
    def loadJsonMetadata(cls, file_loc: str) -> dict:

        with open(file_loc, 'r') as json_file:
            data=json_file.read()

        # parse file
        return json.loads(data)
