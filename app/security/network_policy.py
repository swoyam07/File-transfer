"""
Keeps transfers on the local network.

The receiver only accepts connections from configured address ranges (private
LAN, link-local direct cable, loopback by default), and the sender refuses to
connect to a public internet address unless explicitly allowed.
"""

from __future__ import annotations

import ipaddress
import socket

DEFAULT_ALLOWED_NETWORKS = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fe80::/10",
    "fc00::/7",
)


class NetworkPolicyError(Exception):
    pass


def parse_networks(values: list[str] | tuple[str, ...]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError as exc:
            raise NetworkPolicyError(f"Invalid network range: {value}") from exc
    return networks


class PeerAllowList:
    def __init__(self, networks: list[str] | tuple[str, ...] = DEFAULT_ALLOWED_NETWORKS) -> None:
        self._networks = parse_networks(networks)

    def is_allowed(self, host: str) -> bool:
        try:
            address = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(address in network for network in self._networks)


def resolve_lan_address(host: str, port: int, *, allow_remote: bool) -> str:
    """Resolve host to an IP address and make sure it is on the local network."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkPolicyError(f"Cannot resolve receiver address: {host}") from exc
    address = infos[0][4][0]
    if not allow_remote:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise NetworkPolicyError(
                f"Receiver address {address} is not on the local network. "
                "Set app.allow_remote_connections = true to override."
            )
    return address
