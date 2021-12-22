from string import Template

class Templater:

    LINE_BREAK_REPLACEMENT_YT = chr(13) + chr(10) + chr(13) + chr(10)
    LINE_BREAK_REPLACEMENT_AO = "<br /><br />"

    def __init__(self, title_template_str: str, descr_template_str: str):
        self.titleTemplate = Template(title_template_str)
        self.descriptionTemplate = Template(descr_template_str)
    
    def getTitle(self, fields: dict) -> str:
        return self.titleTemplate.substitute(fields)

    def getDescription(self, fields: dict) -> str:
        return self.descriptionTemplate.substitute(fields)

    @classmethod
    def replaceLbForYT(cls, the_string: str) -> str:
        the_string.replace(" -- ", cls.LINE_BREAK_REPLACEMENT_YT)

    @classmethod
    def replaceLbForAO(cls, the_string: str) -> str:
        the_string.replace(" -- ", cls.LINE_BREAK_REPLACEMENT_AO)
