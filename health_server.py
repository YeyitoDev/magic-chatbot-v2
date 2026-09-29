"""Tiny HTTP health server for Fly.io health checks."""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        # Silenciar logs de cada request del health check
        pass


def start_health_server(port: int | None = None):
    """Start a tiny HTTP server for Fly.io health checks.

    El puerto se lee de la variable de entorno PORT (que define fly.io),
    con fallback a 8080 para alinearse con fly.toml.
    """
    if port is None:
        port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"✅ Health server listening on port {port}")
