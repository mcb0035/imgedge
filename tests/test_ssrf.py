"""SSRF guard + fetch input handling (server.py)."""

import base64
import ipaddress
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


# --- IP classification hardening: IPv4-mapped / NAT64 / CGNAT ---


def _ip(s):
    return ipaddress.ip_address(s)


def test_ipv4_mapped_internal_blocked():
    assert server._ip_is_public(_ip("::ffff:10.0.0.1")) is False
    assert server._ip_is_public(_ip("::ffff:169.254.169.254")) is False


def test_ipv4_mapped_public_allowed():
    assert server._ip_is_public(_ip("::ffff:93.184.216.34")) is True


def test_nat64_embedded_internal_blocked():
    # 64:ff9b::7f00:1 embeds 127.0.0.1; ::a9fe:a9fe embeds 169.254.169.254.
    assert server._ip_is_public(_ip("64:ff9b::7f00:1")) is False
    assert server._ip_is_public(_ip("64:ff9b::a9fe:a9fe")) is False


def test_nat64_embedded_public_allowed():
    # 64:ff9b::5db8:d822 embeds 93.184.216.34.
    assert server._ip_is_public(_ip("64:ff9b::5db8:d822")) is True


def test_nat64_local_prefix_blocked():
    assert server._ip_is_public(_ip("64:ff9b:1::1")) is False


def test_cgnat_blocked():
    assert server._ip_is_public(_ip("100.64.0.1")) is False


# --- URL policy: ports / https-only / host allow-list ---


def test_port_allow_list(monkeypatch):
    monkeypatch.setattr(server, "ALLOWED_PORTS", {80, 443})
    assert server._url_allowed("http://example.com/x.png") is True
    assert server._url_allowed("https://example.com/x.png") is True
    assert server._url_allowed("http://example.com:8080/x.png") is False


def test_ports_any_allows_all(monkeypatch):
    monkeypatch.setattr(server, "ALLOWED_PORTS", None)
    assert server._url_allowed("http://example.com:8080/x.png") is True


def test_https_only(monkeypatch):
    monkeypatch.setattr(server, "FETCH_HTTPS_ONLY", True)
    monkeypatch.setattr(server, "ALLOWED_PORTS", {80, 443})
    assert server._url_allowed("http://example.com/x.png") is False
    assert server._url_allowed("https://example.com/x.png") is True


def test_host_allow_list(monkeypatch):
    monkeypatch.setattr(server, "ALLOW_HOSTS", ("example.com",))
    monkeypatch.setattr(server, "ALLOWED_PORTS", {80, 443})
    monkeypatch.setattr(server, "FETCH_HTTPS_ONLY", False)
    assert server._url_allowed("https://example.com/x.png") is True
    assert server._url_allowed("https://img.example.com/x.png") is True
    assert server._url_allowed("https://evil.com/x.png") is False


# --- response content-type gate ---


def test_content_type_rejects_non_image():
    assert server._content_type_ok("text/html; charset=utf-8") is False
    assert server._content_type_ok("application/json") is False


def test_content_type_allows_image_and_ambiguous():
    assert server._content_type_ok("image/png") is True
    assert server._content_type_ok("application/octet-stream") is True
    assert server._content_type_ok(None) is True
    assert server._content_type_ok("") is True


# --- per-host concurrency cap ---


def test_host_slot_caps_concurrency(monkeypatch):
    monkeypatch.setattr(server, "FETCH_PER_HOST", 2)
    sem = server._acquire_host_slot("cap.example")
    assert sem is not None
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is False  # cap reached
    sem.release()
    sem.release()


def test_host_slot_disabled(monkeypatch):
    monkeypatch.setattr(server, "FETCH_PER_HOST", 0)
    assert server._acquire_host_slot("off.example") is None
