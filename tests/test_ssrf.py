"""SSRF guard + fetch input handling (server.py)."""

import base64
import socket

import pytest

import imgedge.classifier.server as server


def test_public_ip_allowed():
    assert server._is_public_host("8.8.8.8") is True


def test_loopback_blocked():
    assert server._is_public_host("127.0.0.1") is False


def test_private_ranges_blocked():
    for host in ("10.0.0.1", "192.168.1.1", "172.16.0.1"):
        assert server._is_public_host(host) is False


def test_link_local_metadata_blocked():
    # 169.254.169.254 is the classic cloud-metadata SSRF target.
    assert server._is_public_host("169.254.169.254") is False


def test_ipv6_loopback_blocked():
    assert server._is_public_host("::1") is False


def test_fetch_rejects_non_http_scheme():
    assert server.fetch_image_bytes("ftp://example.com/x.png", None) is None
    assert server.fetch_image_bytes("file:///etc/passwd", None) is None


def test_fetch_rejects_loopback_without_network():
    # The host check fails before any socket is opened.
    assert server.fetch_image_bytes("http://127.0.0.1/x.png", None) is None


def test_data_url_decodes():
    raw = b"\x89PNG\r\n\x1a\n payload"
    data = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert server.fetch_image_bytes(None, data) == raw


def test_data_url_without_comma_returns_none():
    # No comma -> the split has no payload part -> handled, returns None.
    assert server.fetch_image_bytes(None, "data:image/png;base64") is None


def _fake_getaddrinfo(ip):
    def _inner(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    return _inner


def test_pinned_resolver_blocks_rebind_to_private(monkeypatch):
    # DNS-rebinding TOCTOU: even if the name resolves to a private address at
    # connect time, the pinned resolver refuses it instead of connecting.
    monkeypatch.setattr(server.socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    with pytest.raises(OSError):
        server._resolve_pinned_addr("evil.example.com", 443)


def test_pinned_resolver_blocks_rebind_to_metadata(monkeypatch):
    # 169.254.169.254 is the cloud-metadata endpoint a rebind attack aims for.
    monkeypatch.setattr(server.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(OSError):
        server._resolve_pinned_addr("evil.example.com", 80)


def test_pinned_resolver_allows_public(monkeypatch):
    monkeypatch.setattr(server.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    sockaddr = server._resolve_pinned_addr("example.com", 443)
    assert sockaddr[0] == "93.184.216.34"
