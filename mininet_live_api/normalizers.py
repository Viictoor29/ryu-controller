class NormalizersMixin:
    """Normalización de payloads JSON recibidos por la API."""

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
