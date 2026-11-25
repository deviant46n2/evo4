import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from evo_core.provider_endpoint import (
    EndpointPolicy,
    PinnedProviderTransport,
    ProviderEndpointError,
)


class CaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.host_headers.append(self.headers.get("Host"))
        self.server.client_ports.append(self.client_address[1])
        self.server.client_addresses.append(self.client_address[0])
        if getattr(self.server, "redirect", False):
            self.send_response(302)
            self.send_header("Location", "https://other.example.test/")
            self.end_headers()
            return
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.server.request_body = self.rfile.read(length)
        self.server.host_headers.append(self.headers.get("Host"))
        self.server.client_ports.append(self.client_address[1])
        self.server.client_addresses.append(self.client_address[0])
        body = b'{"accepted":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PinnedProviderTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
        self.server.host_headers = []
        self.server.client_ports = []
        self.server.client_addresses = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _local_resolver(self, host, port, type=socket.SOCK_STREAM):
        return socket.getaddrinfo("127.0.0.1", port, type=type)

    def test_actual_peer_is_pinned_and_host_header_preserves_hostname(self):
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=self._local_resolver)
        with transport.open_response(self.endpoint, "GET", "/models") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'{"ok":true}')
        self.assertEqual(self.server.host_headers, [f"127.0.0.1:{self.server.server_port}"])
        self.assertEqual(self.server.client_addresses, ["127.0.0.1"])

    def test_every_request_resolves_and_uses_a_new_socket(self):
        calls = []
        def resolver(host, port, type=socket.SOCK_STREAM):
            calls.append((host, port))
            return self._local_resolver(host, port, type)
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        for _ in range(2):
            with transport.open_response(self.endpoint, "GET", "/models") as response:
                self.assertEqual(response.status, 200)
                response.read()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(set(self.server.client_ports)), 2)


    def test_post_body_has_explicit_content_length(self):
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=self._local_resolver)
        with transport.open_response(
            self.endpoint, "POST", "/chat/completions",
            headers={"Content-Type": "application/json"}, body=b'{"hello":"world"}',
        ) as response:
            self.assertEqual(response.status, 200)
            response.read()
        self.assertEqual(self.server.request_body, b'{"hello":"world"}')

    def test_request_path_rejects_query_and_traversal(self):
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=self._local_resolver)
        for route in ("/models?next=https://evil", "/../admin", "//evil.test/path"):
            with self.subTest(route=route):
                with self.assertRaises(ProviderEndpointError):
                    with transport.open_response(self.endpoint, "GET", route):
                        pass

    def test_proxy_environment_does_not_intercept_direct_transport(self):
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=self._local_resolver)
        with patch.dict(os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
        }):
            with transport.open_response(self.endpoint, "GET", "/models") as response:
                self.assertEqual(response.status, 200)
                response.read()

    def test_redirects_are_rejected_not_followed(self):
        self.server.redirect = True
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=self._local_resolver)
        with self.assertRaisesRegex(ProviderEndpointError, "redirects are disabled"):
            with transport.open_response(self.endpoint, "GET", "/models"):
                pass
        self.assertEqual(len(self.server.client_ports), 1)

    def test_non_loopback_http_is_rejected_before_resolution(self):
        calls = []
        transport = PinnedProviderTransport(
            EndpointPolicy(), resolver=lambda *args, **kwargs: calls.append(args) or []
        )
        with self.assertRaises(ProviderEndpointError):
            transport.resolve_destination("http://example.test/v1")
        self.assertEqual(calls, [])

    def test_remote_origin_requires_exact_allowlist(self):
        transport = PinnedProviderTransport(EndpointPolicy(("https://api.example.test",)))
        transport.validate_origin("https://api.example.test/v1")
        with self.assertRaisesRegex(ProviderEndpointError, "not operator-allowlisted"):
            transport.validate_origin("https://evil.example.test/v1")


    def test_dns_rebinding_after_resolution_cannot_change_pinned_peer(self):
        calls = []
        def resolver(host, port, type=socket.SOCK_STREAM):
            calls.append(host)
            if len(calls) == 1:
                return self._local_resolver(host, port, type)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))
            ]
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        with transport.open_response(self.endpoint, "GET", "/models") as response:
            self.assertEqual(response.status, 200)
            response.read()
        self.assertEqual(calls, ["127.0.0.1"])
        self.assertEqual(self.server.client_addresses, ["127.0.0.1"])

    def test_new_request_re_resolves_and_rejects_rebound_destination(self):
        calls = []
        def resolver(host, port, type=socket.SOCK_STREAM):
            calls.append(host)
            if len(calls) == 1:
                return self._local_resolver(host, port, type)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))
            ]
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        with transport.open_response(self.endpoint, "GET", "/models") as response:
            self.assertEqual(response.status, 200)
            response.read()
        with self.assertRaises(ProviderEndpointError):
            with transport.open_response(self.endpoint, "GET", "/models"):
                pass
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.server.client_ports), 1)

    def test_mixed_permitted_and_prohibited_dns_answers_are_rejected(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),
            ]
        transport = PinnedProviderTransport(
            EndpointPolicy(("https://api.example.test",)), resolver=resolver
        )
        with self.assertRaisesRegex(ProviderEndpointError, "prohibited"):
            transport.resolve_destination("https://api.example.test/v1")

    def test_private_destination_requires_exact_allowlisted_origin(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", port))]
        transport = PinnedProviderTransport(
            EndpointPolicy(("https://private.example.test",)), resolver=resolver
        )
        resolved = transport.resolve_destination("https://private.example.test/v1")
        self.assertEqual(str(resolved[-1]), "10.20.30.40")

    def test_ipv4_mapped_loopback_endpoint_is_accepted(self):
        transport = PinnedProviderTransport(EndpointPolicy())
        parsed = transport.validate_origin("http://[::ffff:127.0.0.1]:18997/v1")
        self.assertTrue(parsed[-1])

    def test_ipv4_mapped_ipv6_is_normalized(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", port, 0, 0))]
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        resolved = transport.resolve_destination(self.endpoint)
        self.assertEqual(str(resolved[-1]), "127.0.0.1")

    def test_ipv6_zone_identifiers_are_rejected(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", port, 0, 0))]
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        with self.assertRaisesRegex(ProviderEndpointError, "invalid address"):
            transport.resolve_destination(self.endpoint)

    def test_https_uses_original_hostname_for_sni_and_host_header(self):
        captured = {}
        class FakeTLSContext:
            check_hostname = True
            verify_mode = 2
            def wrap_socket(self, sock, server_hostname):
                captured["server_hostname"] = server_hostname
                return sock
        def resolver(host, port, type=socket.SOCK_STREAM):
            return self._local_resolver("127.0.0.1", port, type)
        transport = PinnedProviderTransport(EndpointPolicy(), resolver=resolver)
        with patch("evo_core.provider_endpoint.ssl.create_default_context", return_value=FakeTLSContext()):
            with transport.open_response(
                f"https://localhost:{self.server.server_port}/v1", "GET", "/models"
            ) as response:
                self.assertEqual(response.status, 200)
                response.read()
        self.assertEqual(captured["server_hostname"], "localhost")
        self.assertEqual(self.server.host_headers[-1], f"localhost:{self.server.server_port}")


    def test_ipv6_dns_scope_id_is_rejected(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:4860:4860::8888", port, 0, 7))
            ]
        transport = PinnedProviderTransport(
            EndpointPolicy(("https://api.example.test",)), resolver=resolver
        )
        with self.assertRaisesRegex(ProviderEndpointError, "scoped address"):
            transport.resolve_destination("https://api.example.test/v1")

    def test_https_ipv6_uses_unbracketed_ip_for_tls_identity(self):
        captured = {}

        class FakeResponse:
            status = 200
            def read(self):
                return b"ok"

        class FakeTLSContext:
            check_hostname = True
            verify_mode = 2
            def wrap_socket(self, sock, server_hostname):
                captured["server_hostname"] = server_hostname
                return sock

        class FakeConnection:
            def __init__(self, host, port, **kwargs):
                captured["connection_host"] = host
                self.sock = None
            def putrequest(self, *args, **kwargs):
                pass
            def putheader(self, name, value):
                if name.lower() == "host":
                    captured["host_header"] = value
            def endheaders(self, body):
                pass
            def getresponse(self):
                return FakeResponse()
            def close(self):
                pass

        def resolver(host, port, type=socket.SOCK_STREAM):
            return [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:4860:4860::8888", port, 0, 0))
            ]

        endpoint = "https://[2001:4860:4860::8888]/v1"
        transport = PinnedProviderTransport(
            EndpointPolicy(("https://[2001:4860:4860::8888]",)), resolver=resolver
        )
        with (
            patch.object(transport, "_connect_pinned", return_value=object()),
            patch("evo_core.provider_endpoint.ssl.create_default_context", return_value=FakeTLSContext()),
            patch("evo_core.provider_endpoint.http.client.HTTPSConnection", FakeConnection),
        ):
            with transport.open_response(endpoint, "GET", "/models") as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(captured["server_hostname"], "2001:4860:4860::8888")
        self.assertEqual(captured["connection_host"], "[2001:4860:4860::8888]")
        self.assertEqual(captured["host_header"], "[2001:4860:4860::8888]")

    def test_connection_failure_does_not_fall_back_to_another_dns_answer(self):
        def resolver(host, port, type=socket.SOCK_STREAM):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.4.4", port)),
            ]
        transport = PinnedProviderTransport(
            EndpointPolicy(("https://api.example.test",)), resolver=resolver
        )
        with patch.object(transport, "_connect_pinned", side_effect=OSError("offline")) as connect:
            with self.assertRaises(ProviderEndpointError):
                with transport.open_response(
                    "https://api.example.test/v1", "GET", "/models"
                ):
                    pass
        connect.assert_called_once()

    def test_peer_identity_mismatch_is_closed_and_rejected(self):
        class FakeSocket:
            closed = False
            def settimeout(self, timeout):
                pass
            def connect(self, target):
                pass
            def getpeername(self):
                return ("127.0.0.2", 80)
            def close(self):
                self.closed = True
        fake = FakeSocket()
        with patch("evo_core.provider_endpoint.socket.socket", return_value=fake):
            with self.assertRaisesRegex(ProviderEndpointError, "invalid address|pinned provider address"):
                PinnedProviderTransport._connect_pinned(
                    __import__("ipaddress").ip_address("127.0.0.1"), 80, 1
                )
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
