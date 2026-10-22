import socket
import ssl
from unittest import mock

import pytest

from src import clearoutside

LAT, LON = "52.23", "21.01"  # Warsaw

PAGE = [
    b"<h1>Forecast for Test Town (1.00, 2.00)</h1>\n",
    b"<h2>Generated: 2026-01-01 12:00. Timezone: Europe/Warsaw<</h2>\n",
    b'<div class="fc_day" id="day_0">\n',
    b'<div class="fc_day_date"><span>Mon</span>5<br></div>\n',
    b'<div class="fc_hour_ratings">\n',
    b'<li class="fc_good">20</li><li class="fc_bad">21</li></ul>\n',
    b'<div class="fc_detail_label"><span>Total Clouds (%)</span></div>\n',
    b'<ul><li>10</li><li>90</li></ul>\n',
    b'<div class="fc_detail_label"><span>Temperature (C)</span></div>\n',
    b'<ul><li>3</li><li>2</li></ul>\n',
]

# Kept to build a genuine TLS context while ssl.SSLContext is patched.
REAL_SSL_CONTEXT = ssl.SSLContext
REAL_GETADDRINFO = socket.getaddrinfo


class CPythonSocket:
    """Gives a CPython TLS socket the write/readline API that MicroPython sockets have."""

    def __init__(self, sock: ssl.SSLSocket) -> None:
        self._sock = sock
        self._file = sock.makefile("rb")  # pyright: ignore[reportAttributeAccessIssue] - The workspace's MicroPython ssl stubs lack CPython's SSLSocket.makefile.

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def readline(self) -> bytes:
        return self._file.readline()

    def close(self) -> None:
        self._file.close()
        self._sock.close()


def ipv4_getaddrinfo(host: str, port: int) -> list[tuple]:
    # socket.socket() is AF_INET, but CPython may return IPv6 addresses first.
    return REAL_GETADDRINFO(host, port, socket.AF_INET, socket.SOCK_STREAM)


def wrap_socket(sock: socket.socket, server_hostname: str | None = None) -> CPythonSocket:
    tls = REAL_SSL_CONTEXT(ssl.PROTOCOL_TLS_CLIENT)
    tls.load_default_certs()
    sock.settimeout(30)
    return CPythonSocket(tls.wrap_socket(sock, server_hostname=server_hostname))


def test_parse() -> None:
    data = clearoutside.parse(PAGE, keep=("total_cloud", "temp"))

    assert data["location"] == "Test Town"
    assert data["generated"] == "2026-01-01 12:00"
    assert len(data["days"]) == 1
    day = data["days"][0]
    assert day["hours"] == [20, 21]
    assert day["rating"] == [0, 2]
    assert day["rows"] == {"total_cloud": [10, 90], "temp": [3, 2]}


@mock.patch("socket.getaddrinfo", new=lambda host, port: [(None, None, None, "", ("1.2.3.4", port))])
@mock.patch("ssl.SSLContext")
@mock.patch("socket.socket")
def test_fetch(sock_cls: mock.MagicMock, ssl_context: mock.MagicMock) -> None:
    sock = sock_cls.return_value
    ssl_context.return_value.wrap_socket.return_value = sock
    lines = iter([b"HTTP/1.0 200 OK\r\n", b"Content-Type: text/html\r\n", b"\r\n", *PAGE])
    sock.readline.side_effect = lambda: next(lines, b"")

    data = clearoutside.fetch(50.06, 19.94, keep=("temp",), view="midday")

    sock.connect.assert_called_once_with(("1.2.3.4", 443))
    (request,), _ = sock.write.call_args
    assert request.startswith(b"GET /forecast/50.06/19.94?view=midday HTTP/1.0\r\n")
    sock.close.assert_called_once_with()
    assert data["location"] == "Test Town"
    assert data["days"][0]["rows"] == {"temp": [3, 2]}


@pytest.mark.live
@mock.patch("socket.getaddrinfo", new=ipv4_getaddrinfo)
@mock.patch("ssl.SSLContext")
def test_fetch_live(ssl_context: mock.MagicMock) -> None:
    # Real network; only the MicroPython-style socket calls in `fetch` are adapted to CPython.
    ssl_context.return_value.wrap_socket.side_effect = wrap_socket

    data = clearoutside.fetch(LAT, LON, keep=("total_cloud",), view=clearoutside.VIEW)

    assert data["location"]
    assert data["generated"]
    assert data["days"]
    assert data["days"][0]["hours"]
    assert len(data["days"][0]["rating"]) == len(data["days"][0]["hours"])