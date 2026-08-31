from __future__ import annotations

import requests

from yahoo_fantasy_data.config import Settings
from yahoo_fantasy_data.errors import YahooAuthenticationError
from yahoo_fantasy_data.yahoo import YahooHTTPClient


class Response:
    status_code = 401
    text = "no"

    def json(self):
        return {}


class Session:
    headers: dict[str, str] = {}

    def mount(self, *args):
        pass

    def get(self, *args, **kwargs):
        return Response()


def test_http_maps_unauthorized_to_authentication_error() -> None:
    client = YahooHTTPClient(Settings(), session=Session())
    try:
        client.get("league/1")
    except YahooAuthenticationError:
        return
    raise AssertionError("expected YahooAuthenticationError")
