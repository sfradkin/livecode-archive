import configparser

class ConfigReader:
    
    @classmethod
    def getConfig(cls, file_loc: str) -> configparser.ConfigParser:
        config = configparser.ConfigParser()
        config.read(file_loc)
        return config
