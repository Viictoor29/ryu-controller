class LinkServiceMixin:
    """Creación, borrado y comparación de enlaces Mininet."""

    def add_link(self, body):
        with self.lock:
            return self._add_link_locked(body)

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

        ofport_results = []

        if n1 in self.net.switches:
            ofport_results.append(
                self.attach_switch_intf(n1, link.intf1, link_spec.get("port1"))
            )

        if n2 in self.net.switches:
            ofport_results.append(
                self.attach_switch_intf(n2, link.intf2, link_spec.get("port2"))
            )

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
            "ofports": ofport_results,
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
