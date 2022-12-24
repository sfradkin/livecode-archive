import json

import pytest
import requests

from utils.jsonloader import JsonLoader


class MockJsonResponse:
    @staticmethod
    def json():
        return json.loads(
            '{\
            "count": 113,\
            "next": null,\
            "previous": null,\
            "results": [\
                {\
                "url": "https://muxy.tidalcycles.org/streams/804/",\
                "recordings": [\
                    "https://muxy.tidalcycles.org/recordings/longest-night/9437ec63-bdf9-4eaa-9988-9ef6a3407b6e-21-Dec-21-13:02:13.flv"\
                ],\
                "key": "9437ec63-bdf9-4eaa-9988-9ef6a3407b6e",\
                "publisher_name": "Santiago Ramírez Camarena",\
                "publisher_email": "a@a.com",\
                "description": "Tidal and other stuff",\
                "location": "Lima, Perú",\
                "timezone": "America/Lima",\
                "starts_at": "2021-12-21T13:00:00Z",\
                "ends_at": "2021-12-21T13:20:00Z",\
                "live_at": null,\
                "event": "https://muxy.tidalcycles.org/events/8/"\
                }\
            ]\
        }'
        )


# monkeypatched requests.get moved to a fixture
@pytest.fixture
def mock_response(monkeypatch):
    """Requests.get() mocked to return the mock json response."""

    def mock_get(*args, **kwargs):
        return MockJsonResponse()

    monkeypatch.setattr(requests, "get", mock_get)


def test_loadJsonMetadataFromUrl(mock_response):

    headers = {"accept": "application/json", "Authorization": "Api-Key aaaaaaa"}
    url = "https://muxy.tidalcycles.org/streams/?event__id=8"

    result = JsonLoader.loadJsonMetadataFromUrl(url, headers)

    print(f"this should be the mock result: {result}")

    assert result["count"] == 113
