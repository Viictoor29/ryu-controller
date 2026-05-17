import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse


class HttpServerMixin:
    """Servidor HTTP y rutas REST de la API de Mininet."""

    def start(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                print("[mininet-api] " + fmt % args)

            def _send_json(self, data, status=200):
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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

            def _path(self):
                return urllib.parse.urlparse(self.path).path

            def do_OPTIONS(self):
                self._send_json({}, status=200)

            def do_GET(self):
                try:
                    path = self._path()
                    if path == "/api/mininet/status":
                        self._ok(service.status())
                    elif path == "/api/mininet/topology/export":
                        self._ok(service.export_topology())
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except Exception as e:
                    self._error(e, status=500)

            def do_POST(self):
                try:
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
                except Exception as e:
                    self._error(e, status=400)

            def do_DELETE(self):
                try:
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
