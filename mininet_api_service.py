import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.parse


class MininetAPIService:
    """
    API REST mínima para modificar una red Mininet viva.

    Importante:
    - Este servicio NO es una API aparte que cree otro Mininet.
    - Debe ejecutarse dentro del mismo proceso que creó el objeto `net`.
    - El runner `mininet_runner_api.py` ya lo hace al instanciar MininetAPIService(net, ...).

    Endpoints principales:
    - GET  /api/mininet/status
    - GET  /api/mininet/topology/export
    - POST /api/mininet/topology/apply
    - POST /api/mininet/topology/clear
    - POST /api/mininet/hosts
    - POST /api/mininet/switches
    - POST /api/mininet/links
    - POST /api/mininet/links/add
    - POST /api/mininet/links/delete
    - DELETE /api/mininet/hosts/{name}
    - DELETE /api/mininet/switches/{name}
    - DELETE /api/mininet/links
    - POST /api/mininet/pingall
    """

    def __init__(self, net, host="127.0.0.1", port=8081, ryu_api_url="http://127.0.0.1:8080"):
        self.net = net
        self.host = host
        self.port = int(port)
        self.server = None
        self.thread = None
        self.lock = threading.RLock()
        self.ryu_api_url = ryu_api_url.rstrip("/")
        self.last_applied_scenario = None

    # ------------------------------------------------------------------
    # HTTP server
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Estado / exportación
    # ------------------------------------------------------------------
    def status(self):
        with self.lock:
            return {
                "hosts": [host.name for host in sorted(self.net.hosts, key=lambda h: h.name)],
                "switches": [sw.name for sw in sorted(self.net.switches, key=lambda s: s.name)],
                "links": [str(link) for link in self.net.links],
                "topology": self.export_topology_locked(),
            }

    def export_topology(self):
        with self.lock:
            return self.export_topology_locked()

    def export_topology_locked(self):
        switches = []
        hosts = []
        links = []

        switch_by_name = {sw.name: sw for sw in self.net.switches}
        host_by_name = {host.name: host for host in self.net.hosts}

        for sw in sorted(self.net.switches, key=lambda s: s.name):
            switches.append({
                "name": sw.name,
                "dpid": self.dpid_from_switch(sw),
            })

        hosts_by_name = {}
        for host in sorted(self.net.hosts, key=lambda h: h.name):
            host_data = {
                "name": host.name,
                "ip": self.safe_host_ip(host),
                "mac": self.safe_host_mac(host),
            }
            hosts_by_name[host.name] = host_data
            hosts.append(host_data)

        for link in list(self.net.links):
            n1 = link.intf1.node
            n2 = link.intf2.node
            n1_name = n1.name
            n2_name = n2.name
            p1 = self.port_from_intf(link.intf1)
            p2 = self.port_from_intf(link.intf2)

            n1_is_sw = n1_name in switch_by_name
            n2_is_sw = n2_name in switch_by_name
            n1_is_host = n1_name in host_by_name
            n2_is_host = n2_name in host_by_name

            if n1_is_sw and n2_is_sw:
                links.append({
                    "type": "switch-link",
                    "src": {"node": n1_name, "dpid": self.dpid_from_switch(n1), "port_no": p1},
                    "dst": {"node": n2_name, "dpid": self.dpid_from_switch(n2), "port_no": p2},
                })
                continue

            if n1_is_host and n2_is_sw:
                hosts_by_name[n1_name]["switch"] = n2_name
                hosts_by_name[n1_name]["switch_dpid"] = self.dpid_from_switch(n2)
                hosts_by_name[n1_name]["switch_port"] = p2
                continue

            if n2_is_host and n1_is_sw:
                hosts_by_name[n2_name]["switch"] = n1_name
                hosts_by_name[n2_name]["switch_dpid"] = self.dpid_from_switch(n1)
                hosts_by_name[n2_name]["switch_port"] = p1
                continue

        return {
            "kind": "mininet_live_topology",
            "exported_at": int(time.time()),
            "mininet": {
                "switches": switches,
                "hosts": hosts,
                "links": links,
            },
            "last_applied_scenario": self.last_applied_scenario,
        }

    # ------------------------------------------------------------------
    # Crear nodos/enlaces dinámicamente
    # ------------------------------------------------------------------
    def _require_name(self, body):
        name = str(body.get("name", "")).strip().lower()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
            raise ValueError("Campo 'name' inválido")
        if name in self.net:
            raise ValueError(f"Ya existe un nodo llamado {name}")
        return name

    def add_host(self, body):
        with self.lock:
            host = self._create_host(body)

            result = {
                "name": host.name,
                "ip": self.safe_host_ip(host),
                "mac": self.safe_host_mac(host),
                "state": "created",
            }

            switch_name = body.get("switch") or body.get("switch_name")
            if switch_name:
                link_body = {
                    "node1": host.name,
                    "node2": str(switch_name).lower(),
                }
                if body.get("switch_port") is not None:
                    link_body["port2"] = int(body["switch_port"])
                result["link"] = self._add_link_locked(link_body)

            return result

    def add_switch(self, body):
        with self.lock:
            switch = self._create_switch(body)
            return {
                "name": switch.name,
                "dpid": self.dpid_from_switch(switch),
                "state": "created",
            }

    def add_link(self, body):
        with self.lock:
            return self._add_link_locked(body)

    def _create_host(self, body):
        name = self._require_name(body)

        params = {}
        if body.get("ip"):
            params["ip"] = str(body["ip"])
        if body.get("mac"):
            params["mac"] = str(body["mac"])

        host = self.net.addHost(name, **params)

        try:
            host.startShell()
        except Exception:
            # En algunas versiones/estados Mininet ya lo tiene preparado.
            pass

        return host

    def _create_switch(self, body):
        name = self._require_name(body)
        params = {
            "protocols": body.get("protocols", "OpenFlow13"),
        }
        if body.get("dpid") is not None:
            params["dpid"] = self.format_dpid(body.get("dpid"))

        switch = self.net.addSwitch(name, **params)

        # Importante: NO hacer self.net.build().
        # Solo arrancamos el switch nuevo contra los controladores existentes.
        switch.start(self.net.controllers)
        return switch

    def _add_link_locked(self, body):
        link_spec = self.normalize_link_body(body)
        node1 = link_spec["node1"]
        node2 = link_spec["node2"]

        if node1 not in self.net or node2 not in self.net:
            raise ValueError(f"node1/node2 deben existir en Mininet: {node1}, {node2}")

        params = {}
        for key in ("port1", "port2", "intfName1", "intfName2"):
            if link_spec.get(key) is not None:
                params[key] = link_spec[key]

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
            "port1": self.port_from_intf(link.intf1),
            "port2": self.port_from_intf(link.intf2),
            "intf1": str(link.intf1),
            "intf2": str(link.intf2),
            "link": str(link),
            "state": "created",
        }

    def delete_link(self, body):
        with self.lock:
            link_spec = self.normalize_link_body(body)
            node1 = link_spec["node1"]
            node2 = link_spec["node2"]
            port1 = link_spec.get("port1")
            port2 = link_spec.get("port2")

            if node1 not in self.net or node2 not in self.net:
                raise ValueError(f"node1/node2 deben existir en Mininet: {node1}, {node2}")

            links = self.net.linksBetween(self.net[node1], self.net[node2])
            links = [link for link in links if self.link_matches_ports(link, node1, port1, node2, port2)]

            if not links:
                raise ValueError(f"No existe enlace entre {node1} y {node2} con los puertos indicados")

            removed = []
            ryu_forget_results = []

            for link in list(links):
                ryu_forget_results.extend(self.notify_ryu_before_link_delete(link))
                removed.append({
                    "link": str(link),
                    "intf1": str(link.intf1),
                    "intf2": str(link.intf2),
                    "port1": self.port_from_intf(link.intf1),
                    "port2": self.port_from_intf(link.intf2),
                })
                self.net.delLink(link)

            return {
                "removed": removed,
                "removed_count": len(removed),
                "ryu_forget_results": ryu_forget_results,
                "state": "deleted",
            }

    # ------------------------------------------------------------------
    # Cargar escenario completo desde la web/controller
    # ------------------------------------------------------------------
    def apply_topology(self, body):
        scenario = self.normalize_scenario_body(body)
        mininet_spec = scenario["mininet"]

        with self.lock:
            clear_result = self.clear_topology_locked(notify_ryu=False)

            created_switches = []
            created_hosts = []
            created_links = []
            skipped_links = []
            seen_link_keys = set()

            for switch in mininet_spec.get("switches", []) or []:
                created_switches.append(self._create_switch(switch).name)

            for host in mininet_spec.get("hosts", []) or []:
                created_hosts.append(self._create_host(host).name)

            # Primero enlaces explícitos. Pueden ser switch-switch o host-switch.
            for link in mininet_spec.get("links", []) or []:
                try:
                    normalized = self.normalize_link_body(link)
                    key = self.normalized_link_key(normalized)
                    if key in seen_link_keys:
                        skipped_links.append({"link": link, "reason": "duplicated"})
                        continue
                    seen_link_keys.add(key)
                    created_links.append(self._add_link_locked(normalized))
                except Exception as e:
                    raise RuntimeError(f"Error creando link {link}: {e}")

            # Después host.switch para mantener compatibilidad con el export/import.
            for host in mininet_spec.get("hosts", []) or []:
                host_name = str(host.get("name", "")).lower()
                switch_name = host.get("switch") or host.get("switch_name")
                switch_dpid = host.get("switch_dpid")
                if not switch_name and switch_dpid is not None:
                    switch_name = self.switch_name_from_dpid(switch_dpid)
                if not host_name or not switch_name:
                    continue

                link_body = {
                    "node1": host_name,
                    "node2": str(switch_name).lower(),
                }
                if host.get("switch_port") is not None:
                    link_body["port2"] = int(host["switch_port"])

                normalized = self.normalize_link_body(link_body)
                key = self.normalized_link_key(normalized)
                if key in seen_link_keys or self.links_between_nodes_exist(normalized["node1"], normalized["node2"]):
                    skipped_links.append({"link": link_body, "reason": "already_exists"})
                    continue

                seen_link_keys.add(key)
                created_links.append(self._add_link_locked(normalized))

            self.last_applied_scenario = scenario

            return {
                "state": "topology_applied",
                "clear": clear_result,
                "created": {
                    "switches": created_switches,
                    "hosts": created_hosts,
                    "links": created_links,
                    "skipped_links": skipped_links,
                },
                "status": self.status(),
            }

    def clear_topology(self, notify_ryu=False):
        with self.lock:
            return self.clear_topology_locked(notify_ryu=notify_ryu)

    def clear_topology_locked(self, notify_ryu=False):
        removed_links = []
        removed_hosts = []
        removed_switches = []

        for link in list(self.net.links):
            if notify_ryu:
                self.notify_ryu_before_link_delete(link)
            removed_links.append(str(link))
            try:
                self.net.delLink(link)
            except Exception as e:
                removed_links.append({"link": str(link), "error": str(e)})

        for host in list(self.net.hosts):
            if notify_ryu:
                try:
                    mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)
                    if mac:
                        self.notify_ryu_forget_host(mac)
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu para olvidar host: {e}")
            removed_hosts.append(host.name)
            try:
                self.net.delHost(host)
            except Exception as e:
                removed_hosts.append({"host": host.name, "error": str(e)})

        for sw in list(self.net.switches):
            removed_switches.append(sw.name)
            try:
                sw.stop()
            except Exception:
                pass
            try:
                self.net.delSwitch(sw)
            except Exception as e:
                removed_switches.append({"switch": sw.name, "error": str(e)})

        self.last_applied_scenario = None

        return {
            "removed_links": removed_links,
            "removed_hosts": removed_hosts,
            "removed_switches": removed_switches,
            "state": "cleared",
        }

    # ------------------------------------------------------------------
    # Borrado de nodos
    # ------------------------------------------------------------------
    def delete_host(self, name):
        with self.lock:
            name = str(name).strip().lower()
            if name not in self.net:
                raise ValueError(f"No existe el host {name}")

            host = self.net[name]
            if host not in self.net.hosts:
                raise ValueError(f"{name} no es un host")

            mac = self.safe_host_mac(host) or self.mac_from_host_name(name)
            ryu_result = None

            if mac:
                try:
                    print(f"[mininet-api] Avisando a Ryu para olvidar host {mac}")
                    ryu_result = self.notify_ryu_forget_host(mac)
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu: {e}")

            removed_links = []
            for intf in list(host.intfList()):
                link = getattr(intf, "link", None)
                if link:
                    removed_links.append(str(link))
                    self.net.delLink(link)

            self.net.delHost(host)

            return {
                "name": name,
                "mac": mac,
                "removed_links": removed_links,
                "ryu_forget_result": ryu_result,
                "state": "deleted",
            }

    def delete_switch(self, name):
        with self.lock:
            name = str(name).strip().lower()
            if name not in self.net:
                raise ValueError(f"No existe el switch {name}")

            sw = self.net.get(name)
            if sw not in self.net.switches:
                raise ValueError(f"{name} no es un switch")

            removed_links = []
            orphan_hosts = []

            for link in list(self.net.links):
                node1 = link.intf1.node
                node2 = link.intf2.node
                if node1 == sw and node2 in self.net.hosts:
                    orphan_hosts.append(node2)
                elif node2 == sw and node1 in self.net.hosts:
                    orphan_hosts.append(node1)

            orphan_hosts = list({host.name: host for host in orphan_hosts}.values())

            for intf in list(sw.intfList()):
                link = getattr(intf, "link", None)
                if link:
                    removed_links.append(str(link))
                    self.net.delLink(link)

            deleted_hosts = []
            for host in orphan_hosts:
                if host.name not in self.net:
                    continue
                mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)
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
                    "ryu_forget_result": ryu_result,
                })

            try:
                sw.stop()
            except Exception:
                pass
            self.net.delSwitch(sw)

            return {
                "name": name,
                "removed_links": removed_links,
                "removed_links_count": len(removed_links),
                "deleted_hosts_count": len(deleted_hosts),
                "deleted_hosts": deleted_hosts,
                "state": "deleted",
            }

    # ------------------------------------------------------------------
    # Ping
    # ------------------------------------------------------------------
    def ping_all(self):
        with self.lock:
            loss = self.net.pingAll()
            return {"packet_loss_percent": loss}

    # ------------------------------------------------------------------
    # Normalización / helpers
    # ------------------------------------------------------------------
    def normalize_scenario_body(self, body):
        if not isinstance(body, dict):
            raise ValueError("El body debe ser un objeto JSON")

        if isinstance(body.get("scenario"), dict):
            body = body["scenario"]

        if isinstance(body.get("mininet"), dict):
            mininet_spec = body["mininet"]
        elif any(key in body for key in ("switches", "hosts", "links")):
            mininet_spec = {
                "switches": body.get("switches", []) or [],
                "hosts": body.get("hosts", []) or [],
                "links": body.get("links", []) or [],
            }
        else:
            raise ValueError("Formato no reconocido. Usa {'mininet': {...}} o switches/hosts/links.")

        switches = []
        for index, switch in enumerate(mininet_spec.get("switches", []) or [], start=1):
            if not isinstance(switch, dict):
                switch = {"name": str(switch)}
            name = str(switch.get("name") or switch.get("id") or f"s{index}").lower()
            dpid = switch.get("dpid") or self.dpid_from_name(name)
            switches.append({
                "name": name,
                "dpid": str(int(str(dpid), 16) if self.looks_hex_dpid(dpid) else int(dpid)),
                "protocols": switch.get("protocols", "OpenFlow13"),
            })

        hosts = []
        for index, host in enumerate(mininet_spec.get("hosts", []) or [], start=1):
            if not isinstance(host, dict):
                host = {"name": str(host)}
            name = str(host.get("name") or host.get("id") or f"h{index}").lower()
            ipv4 = list(host.get("ipv4", []) or [])
            ip = host.get("ip") or host.get("ipv4_address") or (ipv4[0] if ipv4 else None)
            item = {
                "name": name,
                "ip": ip,
                "mac": host.get("mac"),
            }
            if host.get("switch"):
                item["switch"] = str(host.get("switch")).lower()
            if host.get("switch_dpid") is not None:
                item["switch_dpid"] = str(host.get("switch_dpid"))
            if host.get("switch_port") is not None:
                item["switch_port"] = int(host.get("switch_port"))
            hosts.append(item)

        links = []
        for link in mininet_spec.get("links", []) or []:
            links.append(link)

        return {
            "kind": body.get("kind", "sdn_topology_scenario"),
            "version": int(body.get("version", 1)),
            "name": body.get("name") or "web-topology",
            "mininet": {
                "switches": switches,
                "hosts": hosts,
                "links": links,
            },
        }

    def normalize_link_body(self, body):
        if not isinstance(body, dict):
            raise ValueError("El body del link debe ser un objeto JSON")

        if body.get("node1") and body.get("node2"):
            return {
                "node1": str(body.get("node1")).lower(),
                "node2": str(body.get("node2")).lower(),
                "port1": self.optional_int(body.get("port1")),
                "port2": self.optional_int(body.get("port2")),
                "intfName1": body.get("intfName1"),
                "intfName2": body.get("intfName2"),
            }

        src = body.get("src") or body.get("source")
        dst = body.get("dst") or body.get("target")
        if not isinstance(src, dict) or not isinstance(dst, dict):
            raise ValueError("El link debe tener node1/node2 o src/dst")

        src_ep = self.normalize_endpoint(src)
        dst_ep = self.normalize_endpoint(dst)

        return {
            "node1": src_ep["node"],
            "node2": dst_ep["node"],
            "port1": src_ep.get("port_no"),
            "port2": dst_ep.get("port_no"),
            "intfName1": body.get("intfName1"),
            "intfName2": body.get("intfName2"),
        }

    def normalize_endpoint(self, endpoint):
        node = endpoint.get("node") or endpoint.get("name") or endpoint.get("id")
        dpid = endpoint.get("dpid")
        port_no = endpoint.get("port_no") if endpoint.get("port_no") is not None else endpoint.get("port")

        if node is None and dpid is not None:
            node = self.switch_name_from_dpid(dpid)
        if node is not None:
            node = str(node).lower()
        if node is None:
            raise ValueError("Endpoint sin node/name/id/dpid")

        result = {"node": node}
        if port_no is not None:
            result["port_no"] = int(port_no)
        return result

    def normalized_link_key(self, link_spec):
        a = (link_spec.get("node1"), link_spec.get("port1"))
        b = (link_spec.get("node2"), link_spec.get("port2"))
        return tuple(sorted([a, b]))

    def links_between_nodes_exist(self, node1, node2):
        if node1 not in self.net or node2 not in self.net:
            return False
        return bool(self.net.linksBetween(self.net[node1], self.net[node2]))

    def link_matches_ports(self, link, node1, port1, node2, port2):
        endpoints = {
            link.intf1.node.name: self.port_from_intf(link.intf1),
            link.intf2.node.name: self.port_from_intf(link.intf2),
        }
        if node1 not in endpoints or node2 not in endpoints:
            return False
        if port1 is not None and int(endpoints[node1]) != int(port1):
            return False
        if port2 is not None and int(endpoints[node2]) != int(port2):
            return False
        return True

    def notify_ryu_before_link_delete(self, link):
        results = []
        ep1 = self.endpoint_from_intf(link.intf1)
        ep2 = self.endpoint_from_intf(link.intf2)

        if ep1 and ep2:
            try:
                results.append({
                    "kind": "switch-link",
                    "src": ep1,
                    "dst": ep2,
                    "result": self.notify_ryu_forget_link(ep1, ep2),
                })
            except Exception as e:
                print(f"[mininet-api] Error avisando a Ryu para borrar link: {e}")
                results.append({"kind": "switch-link", "src": ep1, "dst": ep2, "error": str(e)})
            return results

        host = None
        for node in (link.intf1.node, link.intf2.node):
            if node in self.net.hosts:
                host = node
                break

        if host is not None:
            mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)
            if mac:
                try:
                    results.append({
                        "kind": "host-link",
                        "host": host.name,
                        "mac": mac,
                        "result": self.notify_ryu_forget_host(mac),
                    })
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu para olvidar host: {e}")
                    results.append({"kind": "host-link", "host": host.name, "mac": mac, "error": str(e)})

        return results

    def endpoint_from_intf(self, intf):
        intf_name = str(intf)
        m = re.match(r"^s(\d+)-eth(\d+)$", intf_name)
        if not m:
            return None
        return {
            "dpid": m.group(1),
            "port_no": int(m.group(2)),
        }

    def port_from_intf(self, intf):
        name = str(intf)
        m = re.match(r"^[a-zA-Z]+\d+-eth(\d+)$", name)
        if m:
            return int(m.group(1))

        try:
            node = intf.node
            return int(node.ports[intf])
        except Exception:
            return None

    def notify_ryu_forget_link(self, src, dst):
        payload = json.dumps({"src": src, "dst": dst}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ryu_api_url}/api/links/forget",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {body}")
            return body

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

    def safe_host_mac(self, host):
        try:
            return host.MAC()
        except Exception:
            return None

    def safe_host_ip(self, host):
        try:
            return host.IP()
        except Exception:
            return None

    def mac_from_host_name(self, name):
        m = re.search(r"\d+$", str(name))
        if not m:
            return None
        n = int(m.group())
        if n < 1 or n > 255:
            return None
        return f"00:00:00:00:00:{n:02x}"

    def dpid_from_switch(self, switch):
        for attr in ("dpid", "defaultDpid"):
            value = getattr(switch, attr, None)
            if value:
                try:
                    return str(int(str(value), 16))
                except Exception:
                    try:
                        return str(int(value))
                    except Exception:
                        pass
        return self.dpid_from_name(switch.name)

    def dpid_from_name(self, name):
        m = re.search(r"(\d+)$", str(name))
        if not m:
            raise ValueError(f"No se pudo inferir dpid de {name}")
        return str(int(m.group(1)))

    def switch_name_from_dpid(self, dpid):
        return f"s{int(str(dpid), 16) if self.looks_hex_dpid(dpid) else int(dpid)}"

    def format_dpid(self, dpid):
        value = int(str(dpid), 16) if self.looks_hex_dpid(dpid) else int(dpid)
        return f"{value:016x}"

    def looks_hex_dpid(self, value):
        text = str(value).strip().lower()
        return text.startswith("0x") or bool(re.search(r"[a-f]", text))

    def optional_int(self, value):
        if value is None or value == "":
            return None
        return int(value)
