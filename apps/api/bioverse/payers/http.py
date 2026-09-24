"""HttpClearinghouse: posts X12 to a real clearinghouse over HTTPS.

Configuration:
- `BIOVERSE_CLEARINGHOUSE_URL`: the clearinghouse's base URL (https; http only for localhost).
- The payer connection's `credentials_secret_name`: the NAME of an environment variable (mounted from
  Secret Manager in the cloud) that holds the API token. The token is read at call time and never
  stored or logged.

Endpoints, relative to the base URL. Clearinghouses differ, so adjust these to your contract:
    GET  /health         connection test
    POST /eligibility    270 in, 271 out          (Content-Type: application/edi-x12)
    POST /claims         837 in, 277CA out
    GET  /remittances    any waiting 835 interchanges, concatenated

Not exercised against a live service in tests: only construction and error handling are.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from bioverse.payers.gateway import ConnectionTest, GatewayError, PayerGateway

SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class HttpClearinghouse(PayerGateway):
    simulated = False
    label = "http-clearinghouse"

    def __init__(self, url: str | None = None, secret_name: str | None = None, timeout: float = 20.0,
                 opener: Any = None):
        url = (url or os.getenv("BIOVERSE_CLEARINGHOUSE_URL") or "").strip()
        if not url:
            raise GatewayError("BIOVERSE_CLEARINGHOUSE_URL is not set, so there is no clearinghouse to send to.")
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise GatewayError(f"BIOVERSE_CLEARINGHOUSE_URL '{url}' is not a valid URL.")
        if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
            raise GatewayError("The clearinghouse URL must use https (plain http is allowed only for localhost).")
        if secret_name is not None and not SECRET_NAME.match(secret_name):
            raise GatewayError("The credentials secret name must look like CLEARINGHOUSE_API_TOKEN "
                               "(capital letters, digits and underscores). Enter the secret's name, not its value.")
        self.base_url = url.rstrip("/")
        self.secret_name = secret_name
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _token(self) -> str | None:
        if not self.secret_name:
            return None
        value = os.getenv(self.secret_name)
        if not value:
            raise GatewayError(f"The secret {self.secret_name} is not available in this environment.")
        return value

    def _request(self, method: str, path: str, body: str | None = None) -> str:
        headers = {"Accept": "application/edi-x12, text/plain"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/edi-x12"
            data = body.encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        host = urlparse(self.base_url).hostname
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise GatewayError(f"The clearinghouse refused our credentials (HTTP {exc.code}). "
                                   f"Check the secret {self.secret_name or '(none set)'}.") from None
            raise GatewayError(f"The clearinghouse returned HTTP {exc.code} for {path}.") from None
        except urllib.error.URLError as exc:
            raise GatewayError(f"Could not reach the clearinghouse at {host}: {exc.reason}.") from None
        except TimeoutError:
            raise GatewayError(f"The clearinghouse at {host} did not answer within {int(self.timeout)} seconds.") from None

    def test_connection(self, payer: dict[str, Any]) -> ConnectionTest:
        self._request("GET", "/health")
        return ConnectionTest(True, f"Reached the clearinghouse at {urlparse(self.base_url).hostname}.")

    def eligibility(self, x12_270: str) -> str:
        return self._request("POST", "/eligibility", x12_270)

    def submit_claims(self, x12_837: str) -> str:
        return self._request("POST", "/claims", x12_837)

    def fetch_remittances(self, payer: dict[str, Any]) -> list[str]:
        text = self._request("GET", f"/remittances?payer_id={payer['payer_id']}")
        parts = re.split(r"(?=ISA.{2}00)", text.strip())
        return [p for p in parts if p.startswith("ISA")]
