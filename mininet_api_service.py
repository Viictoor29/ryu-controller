import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.parse


class MininetAPIService:
    """
    API REST mínima para modificar una red Mininet viva.
    Debe ejecutarse dentro del mismo proceso que creó el objeto `net`.
    """
    def __init__(self, net, host="127.0.0.1", port=8081):
        self.net = net
        self.host = host
        self.port = int(port)
        self.server = None
        self.thread = None
        self.lock = threading.RLock()
        self.ryu_api_url = "http://127.0.0.1:8080"

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
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def do_OPTIONS(self):
                self._send_json({}, status=200)

            def do_GET(self):
                try:
                    if self.path == "/api/mininet/status":
                        self._ok(service.status())
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except Exception as e:
                    self._error(e, status=500)

            def do_POST(self):
                try:
                    body = self._body()
                    if self.path == "/api/mininet/hosts":
                        self._ok(service.add_host(body), status=201)
                    elif self.path == "/api/mininet/switches":
                        self._ok(service.add_switch(body), status=201)
                    elif self.path == "/api/mininet/links":
                        self._ok(service.add_link(body), status=201)
                    elif self.path == "/api/mininet/pingall":
                        self._ok(service.ping_all())
                    else:
                        self._error("Endpoint no encontrado", status=404)
                except Exception as e:
                    self._error(e, status=400)

            def do_DELETE(self):
                try:
                    body = self._body()
                    if self.path.startswith("/api/mininet/hosts/"):
                        name = self.path.rsplit("/", 1)[-1]
                        self._ok(service.delete_host(name))
                    elif self.path.startswith("/api/mininet/switches/"):
                        name = self.path.rsplit("/", 1)[-1]
                        self._ok(service.delete_switch(name))
                    elif self.path == "/api/mininet/links":
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

    def _require_name(self, body):
        name = str(body.get("name", "")).strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
            raise ValueError("Campo 'name' inválido")
        if name in self.net:
            raise ValueError(f"Ya existe un nodo llamado {name}")
        return name

    def status(self):
        with self.lock:
            return {
                "hosts": [host.name for host in sorted(self.net.hosts, key=lambda h: h.name)],
                "switches": [sw.name for sw in sorted(self.net.switches, key=lambda s: s.name)],
                "links": [str(link) for link in self.net.links]
            }

    def add_host(self, body):
        with self.lock:
            name = self._require_name(body)

            params = {}
            if body.get("ip"):
                params["ip"] = str(body["ip"])
            if body.get("mac"):
                params["mac"] = str(body["mac"])

            host = self.net.addHost(name, **params)

            host.startShell()

            return {
                "name": host.name,
                "ip": params.get("ip"),
                "mac": params.get("mac"),
                "state": "created"
            }


    def add_switch(self, body):
        with self.lock:
            name = self._require_name(body)

            switch = self.net.addSwitch(
                name,
                protocols=body.get("protocols", "OpenFlow13")
            )

            # Importante: NO hacer self.net.build()
            # Solo arrancamos el switch nuevo contra los controladores existentes.
            switch.start(self.net.controllers)

            return {
                "name": switch.name,
                "state": "created"
            }


    def add_link(self, body):
        with self.lock:
            node1 = str(body.get("node1", "")).strip()
            node2 = str(body.get("node2", "")).strip()

            if node1 not in self.net or node2 not in self.net:
                raise ValueError("node1/node2 deben existir en Mininet")

            params = {}
            for key in ("port1", "port2", "intfName1", "intfName2"):
                if key in body:
                    params[key] = body[key]

            n1 = self.net.get(node1)
            n2 = self.net.get(node2)

            link = self.net.addLink(n1, n2, **params)

            if n1 in self.net.switches:
                n1.attach(link.intf1)

            if n2 in self.net.switches:
                n2.attach(link.intf2)

            if n1 in self.net.hosts:
                n1.configDefault()

            if n2 in self.net.hosts:
                n2.configDefault()

            return {
                "node1": node1,
                "node2": node2,
                "intf1": str(link.intf1),
                "intf2": str(link.intf2),
                "link": str(link),
                "state": "created"
            }

    def delete_link(self, body):
        with self.lock:
            node1 = str(body.get("node1", "")).strip()
            node2 = str(body.get("node2", "")).strip()
            if node1 not in self.net or node2 not in self.net:
                raise ValueError("node1/node2 deben existir en Mininet")

            links = self.net.linksBetween(self.net[node1], self.net[node2])
            if not links:
                raise ValueError(f"No existe enlace entre {node1} y {node2}")

            removed = []
            for link in list(links):
                self.net.delLink(link)
                removed.append(str(link))
            return {"removed": removed}
        
    def notify_ryu_forget_host(self, mac):
        if not mac:
            raise RuntimeError("No tengo MAC del host, no puedo avisar a Ryu")

        safe_mac = urllib.parse.quote(str(mac).lower(), safe="")
        url = f"{self.ryu_api_url}/api/hosts/forget/{safe_mac}"

        req = urllib.request.Request(url, method="DELETE")

        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {body}")
            return body
    
    def mac_from_host_name(self, name):
        m = re.search(r"\d+$", name)
        if not m:
            return None

        n = int(m.group())
        if n < 1 or n > 255:
            return None

        return f"00:00:00:00:00:{n:02x}"

    def delete_host(self, name):
        with self.lock:
            if name not in self.net:
                raise ValueError(f"No existe el host {name}")

            host = self.net[name]
            mac = None
            ryu_result = None

            try:
                mac = host.MAC()
            except Exception:
                mac = None

            if not mac:
                mac = self.mac_from_host_name(name)

            # Avisar a Ryu antes de eliminarlo de Mininet
            if mac:
                try:
                    print(f"[mininet-api] Avisando a Ryu para olvidar host {mac}")
                    ryu_result = self.notify_ryu_forget_host(mac)
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu: {e}")

            # Eliminar enlaces
            for intf in list(host.intfList()):
                link = getattr(intf, "link", None)
                if link:
                    self.net.delLink(link)

            # Eliminar host
            self.net.delHost(host)

            return {
                "name": name,
                "mac": mac,
                "ryu_forget_result": ryu_result,
                "state": "deleted"
            }

    def delete_switch(self, name):
        with self.lock:
            if name not in self.net:
                raise ValueError(f"No existe el switch {name}")

            sw = self.net.get(name)

            if sw not in self.net.switches:
                raise ValueError(f"{name} no es un switch")

            removed_links = []
            orphan_hosts = []

            # Detectar hosts conectados directamente al switch
            for link in list(self.net.links):
                intf1 = link.intf1
                intf2 = link.intf2
                node1 = intf1.node
                node2 = intf2.node

                if node1 == sw and node2 in self.net.hosts:
                    orphan_hosts.append(node2)
                elif node2 == sw and node1 in self.net.hosts:
                    orphan_hosts.append(node1)

            # Evitar duplicados
            orphan_hosts = list({host.name: host for host in orphan_hosts}.values())

            # Borrar todos los enlaces del switch
            for intf in list(sw.intfList()):
                link = getattr(intf, "link", None)
                if link:
                    removed_links.append(str(link))
                    self.net.delLink(link)

            deleted_hosts = []

            # Borrar hosts que estaban colgados del switch
            for host in orphan_hosts:
                if host.name not in self.net:
                    continue

                try:
                    mac = host.MAC()
                except Exception:
                    mac = None

                if not mac:
                    mac = self.mac_from_host_name(host.name)

                ryu_result = None
                if mac:
                    try:
                        ryu_result = self.notify_ryu_forget_host(mac)
                    except Exception as e:
                        ryu_result = str(e)

                self.net.delHost(host)

                deleted_hosts.append({
                    "name": host.name,
                    "mac": mac,
                    "ryu_forget_result": ryu_result
                })

            self.net.delSwitch(sw)

            return {
                "name": name,
                "removed_links": removed_links,
                "removed_links_count": len(removed_links),
                "deleted_hosts_count": len(deleted_hosts),
                "deleted_hosts": deleted_hosts,
                "state": "deleted"
            }

    def ping_all(self):
        with self.lock:
            loss = self.net.pingAll()
            return {"packet_loss_percent": loss}
