import json
import threading
import os
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse


CLIENT_DISCONNECT_EXCEPTIONS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
API_KEY_HEADER = "X-API-Key"
DEFAULT_NETWORK_API_KEY = "gestordered-tfg-network-api-key-2026"


class HttpServerMixin:
    """Servidor HTTP y rutas REST de la API de Mininet."""

    def start(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                print("[mininet-api] " + fmt % args)

            def _send_json(self, data, status=200):
                body = json.dumps(data).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, X-API-Key")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    self.wfile.flush()
                    return True
                except CLIENT_DISCONNECT_EXCEPTIONS:
                    # El cliente cerró la conexión antes de leer la respuesta
                    # (muy típico con polling de /status desde el navegador).
                    # No es un error del backend: evitamos el traceback y, sobre
                    # todo, no intentamos enviar otro JSON de error por el mismo socket.
                    return False

            def _ok(self, data=None, status=200):
                self._send_json({"ok": True, "data": data or {}}, status=status)

            def _error(self, error, status=400):
                self._send_json({"ok": False, "error": str(error)}, status=status)

            def _body(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length).decode("utf-8")
                if not raw.strip():
                    return {}
                return json.loads(raw)

            def _configured_api_key(self):
                return os.environ.get("NETWORK_API_KEY", DEFAULT_NETWORK_API_KEY)

            def _authorized(self):
                expected_api_key = self._configured_api_key()
                received_api_key = self.headers.get(API_KEY_HEADER, "")
                return bool(expected_api_key) and hmac.compare_digest(received_api_key, expected_api_key)

            def _require_api_key(self):
                if not self._authorized():
                    self._error("No autorizado", status=401)
                    return False
                return True

            def _path(self):
                return urllib.parse.urlparse(self.path).path

            def do_OPTIONS(self):
                self._send_json({}, status=200)

            def do_GET(self):
                try:
                    if not self._require_api_key():
                        return

                    path = self._path()
                    if path == "/api/mininet/status":
                        self._ok(service.status())
                    elif path == "/api/mininet/topology/export":
                        self._ok(service.export_topology())
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except CLIENT_DISCONNECT_EXCEPTIONS:
                    return
                except Exception as e:
                    self._error(e, status=500)

            def do_POST(self):
                try:
                    if not self._require_api_key():
                        return

                    path = self._path()
                    body = self._body()

                    if path == "/api/mininet/hosts":
                        self._ok(service.add_host(body), status=201)
                    elif path == "/api/mininet/switches":
                        self._ok(service.add_switch(body), status=201)
                    elif path in ("/api/mininet/links", "/api/mininet/links/add"):
                        self._ok(service.add_link(body), status=201)
                    elif path == "/api/mininet/links/delete":
                        self._ok(service.delete_link(body))
                    elif path == "/api/mininet/topology/apply":
                        self._ok(service.apply_topology(body))
                    elif path == "/api/mininet/topology/clear":
                        self._ok(service.clear_topology(notify_ryu=bool(body.get("notify_ryu", False))))
                    elif path == "/api/mininet/pingall":
                        self._ok(service.ping_all())
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except CLIENT_DISCONNECT_EXCEPTIONS:
                    return
                except Exception as e:
                    self._error(e, status=400)

            def do_DELETE(self):
                try:
                    if not self._require_api_key():
                        return

                    path = self._path()
                    body = self._body()

                    if path.startswith("/api/mininet/hosts/"):
                        name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
                        self._ok(service.delete_host(name))
                    elif path.startswith("/api/mininet/switches/"):
                        name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
                        self._ok(service.delete_switch(name))
                    elif path in ("/api/mininet/links", "/api/mininet/links/delete"):
                        self._ok(service.delete_link(body))
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except CLIENT_DISCONNECT_EXCEPTIONS:
                    return
                except Exception as e:
                    self._error(e, status=400)

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"*** Mininet API escuchando en http://{self.host}:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
