import pytest
import requests
import json
from utils.jsonloader import JsonLoader
from utils.templater import Templater

VIDEO_TITLE_TEMPLATE = 'TEST - Longest Night Stream December 2021 - $artist_name - $performance_date $performance_time'
VIDEO_DESC_TEMPLATE = 'Longest Night Stream December 2021 live performance by $artist_name from $location -- $user_desc'

result_data = {
                    'archive_id' : 'test',
                    'files' : 'test',
                    'artist_name' : 'test artist',
                    'user_desc' : 'an excellent blend of music',
                    'location' : 'nowhere, US',
                    'performance_date' : '2021-12-20',
                    'performance_time' : '00:00',
                    'tags' : 'tag1, tag2'               
                }

def test_templateDescription():
    templates = Templater(VIDEO_TITLE_TEMPLATE, VIDEO_DESC_TEMPLATE)

    desc = templates.getDescription(result_data)

    print(f"after getDescription: {desc}")

    assert 'Longest Night Stream December 2021 live performance by test artist from nowhere, US -- an excellent blend of music' == desc

def test_templateReplaceLbForYT():
    templates = Templater(VIDEO_TITLE_TEMPLATE, VIDEO_DESC_TEMPLATE)

    desc = templates.getDescription(result_data)

    desc = Templater.replaceLbForYT(desc)

    print(f"after replacing line breaks: {desc}")

    assert 'Longest Night Stream December 2021 live performance by test artist from nowhere, US' +chr(13) + chr(10) + chr(13) + chr(10) + 'an excellent blend of music' == desc
