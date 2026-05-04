#!/usr/bin/env python3
"""
serve.py — Tiny local HTTP server for previewing generated pages.

Usage:
    python3 serve.py --dir ./output/ --port 3088

Serves the directory over HTTP, prints the URL, and runs in the foreground.
The agent can background it with & to continue other work.
"""

import argparse
import http.server
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Serve a directory over HTTP for local preview."
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Directory to serve (default: current directory)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3088,
        help="Port to listen on (default: 3088)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    serve_dir = Path(args.dir).resolve()
    if not serve_dir.exists():
        print(f"[serve] ERROR: Directory not found: {serve_dir}")
        sys.exit(1)

    os.chdir(serve_dir)

    handler = http.server.SimpleHTTPRequestHandler
    # Suppress noisy request logs
    handler.log_message = lambda *a: None  # type: ignore[method-assign]

    with http.server.HTTPServer((args.host, args.port), handler) as httpd:
        local_url = f"http://localhost:{args.port}"
        print(f"[serve] Serving: {serve_dir}")
        print(f"[serve] URL    : {local_url}")
        print(f"[serve] Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] Stopped.")


if __name__ == "__main__":
    main()
