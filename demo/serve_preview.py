"""Minimal static file server for demo screenshot capture.

Usage:
    python demo/serve_preview.py <port> <directory>

Why this exists instead of ``python -m http.server``:
    ``http.server.HTTPServer.server_bind`` calls ``socket.getfqdn(host)`` at
    bind time. On hosts with slow or misconfigured reverse-DNS this blocks for
    a long time before the server ever starts serving, so Playwright times out
    connecting to ``127.0.0.1`` and screenshot capture fails. Serving through a
    plain ``socketserver.TCPServer`` skips the ``getfqdn`` lookup entirely and
    binds immediately, keeping ``make demo`` reproducible across machines.
"""

from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler
import socketserver
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python demo/serve_preview.py <port> <directory>")

    port = int(sys.argv[1])
    directory = sys.argv[2]
    handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)

    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    with Server(("127.0.0.1", port), handler) as httpd:
        print(f"serving {directory} on http://127.0.0.1:{port}", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
