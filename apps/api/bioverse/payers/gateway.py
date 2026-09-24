"""The PayerGateway interface: how Bioverse exchanges X12 with payers.

Two adapters:

- `SimulatedClearinghouse` (bioverse.payers.simulated): the default. Answers from seeded, fictional
  payer-side member data, deterministically. Clearly a demo: nothing leaves the server.
- `HttpClearinghouse` (bioverse.payers.http): posts X12 to a clearinghouse at BIOVERSE_CLEARINGHOUSE_URL,
  authenticating with the secret whose NAME is on the payer connection.

`gateway_for(conn, organization_id, payer)` picks the adapter from the organization's payer connection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from psycopg import Connection


class GatewayError(Exception):
    """A readable reason the payer could not be reached or refused the exchange."""


@dataclass(frozen=True)
class ConnectionTest:
    ok: bool
    message: str


class PayerGateway(ABC):
    simulated: bool = False
    label: str = "gateway"

    @abstractmethod
    def test_connection(self, payer: dict[str, Any]) -> ConnectionTest:
        """Prove the route to this payer works, without touching a real member."""

    @abstractmethod
    def eligibility(self, x12_270: str) -> str:
        """Send a 270 and return the 271."""

    @abstractmethod
    def submit_claims(self, x12_837: str) -> str:
        """Send an 837 and return the 277CA claim acknowledgment."""

    @abstractmethod
    def fetch_remittances(self, payer: dict[str, Any]) -> list[str]:
        """Collect any 835 remittances waiting for us from this payer."""


def connection_for(conn: Connection, organization_id: str, payer_ref: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text, status, gateway, credentials_secret_name FROM payer_connections
        WHERE organization_id = %s AND payer_ref = %s
        """,
        (organization_id, payer_ref),
    ).fetchone()


def gateway_for(conn: Connection, organization_id: str, payer: dict[str, Any]) -> PayerGateway:
    """The adapter for this organization's connection to `payer`. Raises GatewayError when not connected."""
    connection = connection_for(conn, organization_id, payer["id"])
    if connection is None or connection["status"] != "connected":
        raise GatewayError(f"{payer['name']} is not connected. An administrator can connect it under Payer connections.")
    return build_gateway(conn, connection["gateway"], connection["credentials_secret_name"])


def build_gateway(conn: Connection, kind: str, secret_name: str | None) -> PayerGateway:
    if kind == "http":
        from bioverse.payers.http import HttpClearinghouse

        return HttpClearinghouse(secret_name=secret_name)
    from bioverse.payers.simulated import SimulatedClearinghouse

    return SimulatedClearinghouse(conn)
