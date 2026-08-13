"""Thin HTTP client for the My AI backend, mirroring vibe-agent's
desktop/client.py shape (raises APIError on failure, holds a bearer token,
plain methods returning dicts/strings) - but living at the project root
rather than nested inside desktop/, since both the CLI (app/main.py) and
the desktop GUI need it, unlike vibe-agent which only ever has one client.
"""

import requests

BASE_URL = "http://localhost:8000"


class APIError(Exception):
    pass


class APIClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.token: str | None = None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def _raise_for_error(response: requests.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise APIError(detail)

    def register(self, username: str, password: str) -> None:
        response = requests.post(
            f"{self.base_url}/auth/register", json={"username": username, "password": password}, timeout=30
        )
        self._raise_for_error(response)
        self.token = response.json()["token"]

    def login(self, username: str, password: str) -> None:
        response = requests.post(
            f"{self.base_url}/auth/login", json={"username": username, "password": password}, timeout=30
        )
        self._raise_for_error(response)
        self.token = response.json()["token"]

    def logout(self) -> None:
        if self.token:
            requests.post(f"{self.base_url}/auth/logout", headers=self._headers(), timeout=30)
        self.token = None

    def me(self) -> str:
        response = requests.get(f"{self.base_url}/auth/me", headers=self._headers(), timeout=30)
        self._raise_for_error(response)
        return response.json()["username"]

    def chat(self, messages: list, consent_answer: str | None = None, consent_key: str | None = None) -> dict:
        payload = {"messages": messages}
        if consent_answer is not None:
            payload["consent_answer"] = consent_answer
        if consent_key is not None:
            payload["consent_key"] = consent_key
        response = requests.post(f"{self.base_url}/chat", json=payload, headers=self._headers(), timeout=60)
        self._raise_for_error(response)
        return response.json()

    def list_permissions(self) -> dict:
        response = requests.get(f"{self.base_url}/permissions", headers=self._headers(), timeout=30)
        self._raise_for_error(response)
        return response.json()

    def grant(self, resource: str) -> None:
        response = requests.post(
            f"{self.base_url}/permissions/grant", json={"resource": resource}, headers=self._headers(), timeout=30
        )
        self._raise_for_error(response)

    def revoke(self, resource: str) -> None:
        response = requests.post(
            f"{self.base_url}/permissions/revoke", json={"resource": resource}, headers=self._headers(), timeout=30
        )
        self._raise_for_error(response)

    def list_preferences(self) -> dict:
        response = requests.get(f"{self.base_url}/preferences", headers=self._headers(), timeout=30)
        self._raise_for_error(response)
        return response.json()

    def reset_preference(self, key: str) -> bool:
        response = requests.post(
            f"{self.base_url}/preferences/reset", json={"key": key}, headers=self._headers(), timeout=30
        )
        self._raise_for_error(response)
        return response.json()["forgotten"]

    def list_activity(self) -> list:
        response = requests.get(f"{self.base_url}/activity", headers=self._headers(), timeout=30)
        self._raise_for_error(response)
        return response.json()
