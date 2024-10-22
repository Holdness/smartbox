import datetime
import json
import logging
import requests

_MIN_TOKEN_LIFETIME = 60  # Minimum time left before expiry before we refresh (seconds)

_LOGGER = logging.getLogger(__name__)


class Session(object):
    def __init__(self, api_name, basic_auth_credentials, x_referer, x_serialid, username, password):
        self._api_name = api_name
        self._api_host = f"https://api-{self._api_name}.helki.com"
        self._basic_auth_credentials = basic_auth_credentials
        self._x_referer = x_referer
        self._x_serialid = x_serialid
        self._auth({'grant_type': 'password', 'username': username, 'password': password})

    def _auth(self, credentials):
        token_data = '&'.join(f"{k}={v}" for k, v in credentials.items())
        token_headers = {
            'authorization': f'Basic {self._basic_auth_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'x-referer': self._x_referer,
            'x-serialid': self._x_serialid,
        }

        token_url = f"{self._api_host}/client/token"
        response = requests.post(token_url, data=token_data, headers=token_headers)
        r = response.json()
        self._access_token = r['access_token']
        self._refresh_token = r['refresh_token']
        if r['expires_in'] < _MIN_TOKEN_LIFETIME:
            _LOGGER.warning((f"Token expires in {r['expires_in']}s, which is below minimum lifetime "
                             f"of {_MIN_TOKEN_LIFETIME}s - will refresh again on next operation"))
        self._expires_at = datetime.datetime.now() + datetime.timedelta(seconds=r['expires_in'])
        _LOGGER.debug((f"Authenticated session ({credentials['grant_type']}), "
                       f"access_token={self._access_token}, expires at {self._expires_at}"))

    def _has_token_expired(self):
        return (self._expires_at - datetime.datetime.now()) < datetime.timedelta(seconds=_MIN_TOKEN_LIFETIME)

    def _check_refresh(self):
        if self._has_token_expired():
            self._auth({'grant_type': 'refresh_token', 'refresh_token': self._refresh_token})

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "x-referer": self._x_referer,
            "x-serialid": self._x_serialid,
        }

    def _api_request(self, path):
        self._check_refresh()
        api_url = f"{self._api_host}/api/v2/{path}"
        response = requests.get(api_url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def _api_post(self, data, path):
        self._check_refresh()
        api_url = f"{self._api_host}/api/v2/{path}"
        # TODO: json dump
        try:
            data_str = json.dumps(data)
            _LOGGER.debug(f"Posting {data_str} to {api_url}")
            response = requests.post(api_url, data=data_str, headers=self._get_headers())
            response.raise_for_status()
        except requests.HTTPError as e:
            # TODO: logging
            _LOGGER.error(e)
            _LOGGER.error(e.response.json())
            raise
        return response.json()

    def get_api_name(self):
        return self._api_name

    def get_access_token(self):
        return self._access_token

    def get_refresh_token(self):
        return self._refresh_token

    def get_expiry_time(self):
        return self._expires_at

    def get_devices(self):
        response = self._api_request("devs")
        return response['devs']

    def get_grouped_devices(self):
        response = self._api_request("grouped_devs")
        return response

    def get_nodes(self, device_id):
        response = self._api_request(f"devs/{device_id}/mgr/nodes")
        return response['nodes']

    def get_status(self, device_id, node):
        return self._api_request(f"devs/{device_id}/{node['type']}/{node['addr']}/status")

    def set_status(self, device_id, node, status_args):
        data = {k: v for k, v in status_args.items() if v is not None}
        if 'stemp' in data and 'units' not in data:
            raise ValueError("Must supply unit with temperature fields")
        return self._api_post(data=data, path=f"devs/{device_id}/{node['type']}/{node['addr']}/status")

    def get_setup(self, device_id, node):
        return self._api_request(f"devs/{device_id}/{node['type']}/{node['addr']}/setup")

    def set_setup(self, device_id, node, setup_args):
        data = {k: v for k, v in setup_args.items() if v is not None}
        # setup seems to require all settings to be re-posted, so get current
        # values and update
        setup_data = self.get_setup(device_id, node)
        setup_data.update(data)
        return self._api_post(data=setup_data, path=f"devs/{device_id}/{node['type']}/{node['addr']}/setup")

    def get_device_away_status(self, device_id):
        return self._api_request(f"devs/{device_id}/mgr/away_status")

    def set_device_away_status(self, device_id, status_args):
        data = {k: v for k, v in status_args.items() if v is not None}
        return self._api_post(data=data, path=f"devs/{device_id}/mgr/away_status")
