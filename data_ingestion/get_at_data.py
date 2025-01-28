import os
import requests

from base64 import b64encode
from typing import Any

import pandas as pd
from pydantic import BaseModel, computed_field


def basic_auth(username, password):
    token = b64encode(f"{username}:{password}".encode('utf-8')).decode("ascii")
    return f"Basic {token}"


class TrackData(BaseModel):
    track_thumbnail_url: str
    track_name: str
    author_time: float
    top_time: float
    ten_k_time: float

    @computed_field
    def ten_k_percent(self) -> float:
        _time_delta = self.author_time - self.ten_k_time
        return round(100* (_time_delta / self.author_time), 2)

    @computed_field
    def top_percent(self) -> float:
        _time_delta = self.author_time - self.top_time
        return round(100* (_time_delta / self.author_time), 2)

    @computed_field
    def ten_k_delta(self) -> float:
        return self.author_time - self.ten_k_time

    @computed_field
    def top_delta(self) -> float:
        return self.author_time - self.top_time


class TMAPIConnector:
    _ubisoft_auth_ticket: str
    _auth_token: str
    _refresh_token: str
    _auth_header: dict[str, str]

    def __init__(self, ubisoft_email: str, ubisoft_password: str, app_name: str):
        self._get_ubisoft_auth_ticket(ubisoft_email, ubisoft_password, app_name)
        self._get_trackmania_api_tokens()

    def _get_ubisoft_auth_ticket(self, ubisoft_email: str, ubisoft_password: str, app_name: str) -> None:
        request = requests.post(
            url="https://public-ubiservices.ubi.com/v3/profiles/sessions",
            headers={
                "Content-Type": "application/json",
                "Ubi-AppId": "86263886-327a-4328-ac69-527f0d20a237",
                "Authorization": basic_auth(ubisoft_email, ubisoft_password),
                "User-Agent": f"{app_name}/ {ubisoft_email}"
            },
        )
        request.raise_for_status()
        self._ubisoft_auth_ticket = request.json()["ticket"]

    def _parse_access_tokens(self, tokens_dict: dict[str, str]) -> None:
        self._auth_token = tokens_dict["accessToken"]
        self._refresh_token = tokens_dict["refreshToken"]
        self._auth_header = {"Authorization": f"nadeo_v1 t={self._auth_token}"}

    def _get_trackmania_api_tokens(self) -> None:
        request = requests.post(
            url="https://prod.trackmania.core.nadeo.online/v2/authentication/token/ubiservices",
            json={"audience": "NadeoLiveServices"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"ubi_v1 t={self._ubisoft_auth_ticket}",
            },
        )
        request.raise_for_status()
        self._parse_access_tokens(request.json())
        self.cosa = request

    def _refresh_trackmania_api_tokens(self) -> None:
        request = requests.post(
            url="https://prod.trackmania.core.nadeo.online/v2/authentication/token/refresh",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"nadeo_v1 t={self._refresh_token}",
            },
        )
        request.raise_for_status()
        self._parse_access_tokens(request.json())

    # Wrap in _refresh_trackmania_api_tokens method that checks time of token expiration
    def get_campaign_map_ids(self) -> dict[str, Any]:
        request = requests.get(
            url=f"https://live-services.trackmania.nadeo.live/api/token/campaign/official",
            headers=self._auth_header,
            params={"length": 30, "offset": 0},
        )
        request.raise_for_status()
        map_ids: dict[str, dict[str, str]] = {}
        for campaign_info in request.json()["campaignList"]:
            campaign_name = campaign_info["name"]
            map_ids[campaign_name] = {}
            for map in campaign_info["playlist"]:
                map_ids[campaign_name][map["position"] + 1] = map["mapUid"]
            
        return map_ids

    # Wrap in _refresh_trackmania_api_tokens method that checks time of token expiration
    def get_map_data(self, map_id: str, get_keys: list[str]) -> dict[str, Any]:
        request = requests.get(
            url=f"https://live-services.trackmania.nadeo.live/api/token/map/{map_id}",
            headers=self._auth_header,
        )
        request.raise_for_status()
        map_data = request.json()
        return {key: map_data[key] for key in get_keys}

    # Wrap in _refresh_trackmania_api_tokens method that checks time of token expiration
    def get_map_time(self, map_id: str, offset: int) -> int:
        request = requests.get(
            url=(
                f"https://live-services.trackmania.nadeo.live/api/token/leaderboard/group/"
                f"Personal_Best/map/{map_id}/top"
            ),
            params={
                "length": 1,
                "onlyWorld": True,
                "offset": offset,
            },
            headers=self._auth_header,
        )
        request.raise_for_status()
        return request.json()["tops"][0]["top"][0]["score"]


if __name__ == "__main__":

    # Setup API Connection
    api_connector = TMAPIConnector(
        ubisoft_email=os.environ["UBISOFT_EMAIL"],
        ubisoft_password=os.environ["UBISOFT_PASSWORD"],
        app_name="Easiest Campaign AT Investigation",
    )

    # Get map ID's for all maps in campaigns
    map_ids: dict[str, dict[str, str]] = api_connector.get_campaign_map_ids()

    # Get required data for each map
    track_data_list: list[TrackData] = []
    for campaign, track_data in map_ids.items():
        for track_name, track_id in track_data.items():
            map_data = api_connector.get_map_data(track_id, ["authorTime", "thumbnailUrl"])
            track_data_list.append(
                TrackData(
                    track_thumbnail_url=map_data["thumbnailUrl"],
                    track_name=f"{campaign} - {track_name}",
                    author_time=map_data["authorTime"] / 1_000,
                    top_time=api_connector.get_map_time(track_id, 0) / 1_000,
                    ten_k_time=api_connector.get_map_time(track_id, 9_999) / 1_000,
                )
            )
    
    # Format and save data
    df = pd.DataFrame([track_data.dict() for track_data in track_data_list])
    df.rename(
        columns={
            "track_thumbnail_url": "Thumbnail",
            "track_name": "Track Name",
            "author_time":  "Author Time",
            "top_time": "Top Time",
            "ten_k_time": "10k Time",
            "ten_k_percent": "10k Time % Difference",
            "top_percent": "Top Time % Difference",
            "ten_k_delta": "10k Time Difference",
            "top_delta": "Top Time Difference",
        },
        inplace=True,
    )
    df["Completed"] = False
    df.to_csv("data/campaign_data.csv", index=False)
