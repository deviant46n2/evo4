"""Direct, address-pinned HTTP transport for configured provider endpoints.

This module deliberately has no proxy support, connection pool, redirect
following, or alternate-address fallback. Every request creates a new socket,
resolves the hostname again, validates the complete answer set, and connects
to one numeric address while retaining the hostname for Host and TLS checks.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Mapping
from urllib.parse import urlsplit


class ProviderEndpointError(RuntimeError):
    """Endpoint policy or pinned transport failure; messages contain no secrets."""


_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("100.100.100.2"),
    ipaddress.ip_address("fd00:ec2::254"),
}


def _normalized_ip(value):
    if not isinstance(value, str) or "%" in value:
        raise ProviderEndpointError("provider DNS returned an invalid address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ProviderEndpointError("provider DNS returned an invalid address") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address


def _host_for_url(hostname):
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            normalized = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ProviderEndpointError("provider hostname is invalid") from exc
        labels = normalized.split(".")
        if (
            not normalized
            or len(normalized) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise ProviderEndpointError("provider hostname is invalid")
        return normalized
    return f"[{address.compressed}]" if address.version == 6 else address.compressed


def _parse_endpoint(endpoint):
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 2048:
        raise ProviderEndpointError("provider endpoint is invalid")
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ProviderEndpointError("provider endpoint is malformed") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in endpoint
        or "#" in endpoint
        or parsed.query
        or parsed.fragment
        or "%" in hostname
        or parsed.path not in {"", "/", "/v1"}
    ):
        raise ProviderEndpointError("provider endpoint violates URL policy")
    normalized_host = _host_for_url(hostname)
    default_port = 443 if parsed.scheme == "https" else 80
    port = default_port if port is None else port
    if not 1 <= port <= 65535:
        raise ProviderEndpointError("provider endpoint port is invalid")
    try:
        literal = ipaddress.ip_address(hostname)
        if isinstance(literal, ipaddress.IPv6Address) and literal.ipv4_mapped is not None:
            literal = literal.ipv4_mapped
        static_loopback = literal.is_loopback
    except ValueError:
        static_loopback = hostname.rstrip(".").lower() == "localhost"
    if parsed.scheme == "http" and not static_loopback:
        raise ProviderEndpointError("non-loopback provider endpoints require HTTPS")
    authority = normalized_host
    if port != default_port:
        authority = f"{authority}:{port}"
    origin = f"{parsed.scheme}://{authority}"
    return parsed, hostname, normalized_host, port, origin, static_loopback


@dataclass(frozen=True)
class EndpointPolicy:
    allowed_origins: tuple[str, ...] = ()


def normalize_provider_origin(origin):
    """Return a canonical exact origin, rejecting paths and URL credentials."""
    parsed, _, _, _, normalized, _ = _parse_endpoint(origin)
    if parsed.path not in {"", "/"}:
        raise ProviderEndpointError("provider origin entries must not contain a path")
    return normalized


def is_loopback_provider_origin(origin):
    parsed, _, _, _, _, static_loopback = _parse_endpoint(origin)
    return static_loopback


class PinnedProviderTransport:
    """One-request-per-socket transport with DNS and peer-address pinning."""

    def __init__(self, policy: EndpointPolicy, *, resolver=None):
        if not isinstance(policy, EndpointPolicy):
            raise TypeError("policy must be an EndpointPolicy")
        self.policy = policy
        self._resolver = resolver or socket.getaddrinfo

    def _allowed_origins(self):
        normalized = set()
        for entry in self.policy.allowed_origins:
            parsed, _, _, _, origin, static_loopback = _parse_endpoint(entry)
            if parsed.path not in {"", "/"}:
                raise ProviderEndpointError("origin allowlist entries must not contain a path")
            if parsed.scheme != "https" and not static_loopback:
                raise ProviderEndpointError("non-loopback origin allowlist entries must use HTTPS")
            normalized.add(origin)
        return normalized

    def validate_origin(self, endpoint):
        parsed, hostname, normalized_host, port, origin, static_loopback = _parse_endpoint(endpoint)
        allowed = self._allowed_origins()
        if not static_loopback and origin not in allowed:
            raise ProviderEndpointError("provider origin is not operator-allowlisted")
        return parsed, hostname, normalized_host, port, origin, static_loopback

    def resolve_destination(self, endpoint):
        parsed, hostname, normalized_host, port, origin, static_loopback = self.validate_origin(endpoint)
        try:
            answers = self._resolver(hostname, port, type=socket.SOCK_STREAM)
        except Exception as exc:
            raise ProviderEndpointError("provider hostname resolution failed") from exc
        if not answers:
            raise ProviderEndpointError("provider hostname has no usable addresses")
        addresses = []
        for answer in answers:
            try:
                sockaddr = answer[4]
                # Scoped IPv6 destinations are interface-dependent and must
                # never be accepted as globally pinned provider addresses.
                if len(sockaddr) >= 4 and sockaddr[3] != 0:
                    raise ProviderEndpointError("provider DNS returned a scoped address")
                raw = sockaddr[0]
                address = _normalized_ip(raw)
            except (IndexError, TypeError, KeyError) as exc:
                raise ProviderEndpointError("provider DNS returned a malformed answer") from exc
            if address in _METADATA_ADDRESSES:
                raise ProviderEndpointError("provider destination is prohibited")
            if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved:
                raise ProviderEndpointError("provider destination is prohibited")
            if address.is_loopback:
                if not static_loopback:
                    raise ProviderEndpointError("non-local provider hostname resolved to loopback")
            elif static_loopback:
                raise ProviderEndpointError("local provider hostname resolved outside loopback")
            elif address.is_private:
                if origin not in self._allowed_origins():
                    raise ProviderEndpointError("private provider destination is not explicitly approved")
            elif not address.is_global:
                raise ProviderEndpointError("provider destination is not globally routable")
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise ProviderEndpointError("provider hostname has no usable addresses")
        # Deliberately select one address. No Happy Eyeballs or silent fallback.
        return parsed, hostname, normalized_host, port, origin, addresses[0]

    @staticmethod
    def _connect_pinned(address, port, timeout):
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            target = (address.compressed, port, 0, 0) if address.version == 6 else (address.compressed, port)
            sock.connect(target)
            peer = _normalized_ip(sock.getpeername()[0])
            if peer != address:
                raise ProviderEndpointError("connected peer did not match the pinned provider address")
            return sock
        except Exception:
            sock.close()
            raise

    @contextmanager
    def open_response(self, endpoint, method, route, *, headers=None, body=None, timeout=30):
        if not isinstance(method, str) or method.upper() not in {"GET", "POST"}:
            raise ProviderEndpointError("provider HTTP method is not supported")
        if (
            not isinstance(route, str)
            or not route.startswith("/")
            or route.startswith("//")
            or any(char in route for char in ("?", "#", "%", "\\", "\x00", "\r", "\n"))
            or any(segment in {".", ".."} for segment in route.split("/"))
        ):
            raise ProviderEndpointError("provider request path is invalid")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 600:
            raise ProviderEndpointError("provider request timeout is invalid")
        parsed, hostname, normalized_host, port, origin, pinned_ip = self.resolve_destination(endpoint)
        base_path = parsed.path.rstrip("/")
        request_path = (base_path + route) or "/"
        default_port = 443 if parsed.scheme == "https" else 80
        host_header = normalized_host if port == default_port else f"{normalized_host}:{port}"
        if headers is not None and not isinstance(headers, Mapping):
            raise ProviderEndpointError("provider request headers must be a mapping")
        if body is not None and not isinstance(body, (bytes, bytearray, memoryview)):
            raise ProviderEndpointError("provider request body must be bytes")
        connection = None
        raw_socket = None
        try:
            raw_socket = self._connect_pinned(pinned_ip, port, timeout)
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
                    raise ProviderEndpointError("TLS hostname and certificate verification must remain enabled")
                # URL authorities bracket IPv6 literals; TLS reference identities
                # must use the unbracketed IP address.
                tls_server_name = (
                    normalized_host[1:-1]
                    if normalized_host.startswith("[")
                    else normalized_host
                )
                wrapped = context.wrap_socket(raw_socket, server_hostname=tls_server_name)
                raw_socket = None  # ownership transferred to the TLS socket
                connection = http.client.HTTPSConnection(
                    normalized_host, port, timeout=timeout, context=context
                )
                connection.sock = wrapped
            else:
                connection = http.client.HTTPConnection(normalized_host, port, timeout=timeout)
                connection.sock = raw_socket
                raw_socket = None  # ownership transferred to the HTTP connection
            # A fresh connection is used for every request; never reuse or pool.
            connection.putrequest(method.upper(), request_path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host_header)
            connection.putheader("Connection", "close")
            supplied_headers = headers or {}
            seen_headers = set()
            for name, value in supplied_headers.items():
                if not isinstance(name, str) or not isinstance(value, str):
                    raise ProviderEndpointError("provider request headers must be strings")
                lowered = name.lower()
                if lowered in seen_headers:
                    raise ProviderEndpointError("provider request contains duplicate headers")
                seen_headers.add(lowered)
                if lowered in {
                    "host", "connection", "proxy-authorization", "proxy-connection",
                    "content-length", "transfer-encoding",
                }:
                    raise ProviderEndpointError("provider request contains a reserved header")
                if any(ch in name + value for ch in "\r\n"):
                    raise ProviderEndpointError("provider request header is malformed")
                connection.putheader(name, value)
            if body is not None or method.upper() == "POST":
                connection.putheader("Content-Length", str(len(body) if body is not None else 0))
            connection.endheaders(body)
            response = connection.getresponse()
        except ProviderEndpointError:
            if connection is not None:
                connection.close()
            if raw_socket is not None:
                raw_socket.close()
            raise
        except (TimeoutError, socket.timeout) as exc:
            if connection is not None:
                connection.close()
            if raw_socket is not None:
                raw_socket.close()
            raise ProviderEndpointError("provider request timed out") from exc
        except Exception as exc:
            if connection is not None:
                connection.close()
            if raw_socket is not None:
                raw_socket.close()
            raise ProviderEndpointError("pinned provider request failed") from exc

        if 300 <= response.status < 400:
            response.close()
            connection.close()
            raise ProviderEndpointError("provider redirects are disabled")
        try:
            # Exceptions from the consumer must propagate unchanged. In
            # particular, ProviderHTTPError is not a transport failure.
            yield response
        finally:
            connection.close()
