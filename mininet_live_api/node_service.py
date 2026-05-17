import re


class NodeServiceMixin:
    """Creación y borrado dinámico de hosts y switches."""

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

            body_ip = body.get("ip")

            if body_ip is None:
                body_ipv4 = body.get("ipv4")
                if isinstance(body_ipv4, list) and body_ipv4:
                    body_ip = body_ipv4[0]
                else:
                    body_ip = body_ipv4

            body_mac = body.get("mac")

            ip = self.safe_host_ip(host) or body_ip
            mac = self.safe_host_mac(host) or body_mac

            result = {
                "name": host.name,
                "ip": ip,
                "mac": mac,
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
