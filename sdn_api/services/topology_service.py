from ryu.topology.api import get_switch, get_link, get_host


class TopologyService:
    def __init__(self, app, tc_service):
        self.app = app
        self.tc_service = tc_service

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return tuple(sorted([a, b]))

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        No borra enlaces antiguos para poder seguir mostrando enlaces
        deshabilitados manualmente.
        """
        for key in list(self.app.links_inventory.keys()):
            self.app.links_inventory[key]["discovered"] = False

        links = get_link(self.app, None)

        for link in links:
            src_dpid = str(link.src.dpid)
            dst_dpid = str(link.dst.dpid)
            src_port = int(link.src.port_no)
            dst_port = int(link.dst.port_no)

            key = self.make_link_key(src_dpid, src_port, dst_dpid, dst_port)

            if key not in self.app.links_inventory:
                self.app.links_inventory[key] = {
                    "source": src_dpid,
                    "target": dst_dpid,
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "enabled": True,
                    "discovered": True
                }
            else:
                self.app.links_inventory[key]["enabled"] = True
                self.app.links_inventory[key]["discovered"] = True

    def set_link_inventory_state(self, src, dst, enabled):
        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        if key in self.app.links_inventory:
            self.app.links_inventory[key]["enabled"] = bool(enabled)
        else:
            self.app.links_inventory[key] = {
                "source": src["dpid"],
                "target": dst["dpid"],
                "src_port": src["port_no"],
                "dst_port": dst["port_no"],
                "enabled": bool(enabled),
                "discovered": False
            }

    def get_topology_data(self):
        self.sync_links_inventory()

        nodes = []
        edges = []
        seen_nodes = set()

        try:
            switches = get_switch(self.app, None)
        except Exception as e:
            self.app.logger.exception("Error obteniendo switches con get_switch(): %s", e)
            switches = []

        for sw in switches:
            sw_id = str(sw.dp.id)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        for dpid in sorted(self.app.datapaths.keys()):
            sw_id = str(dpid)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        try:
            hosts = get_host(self.app, None)
        except Exception as e:
            self.app.logger.exception("Error obteniendo hosts con get_host(): %s", e)
            hosts = []

        for host in hosts:
            host_id = str(host.mac)
            switch_id = str(host.port.dpid)

            if host_id not in seen_nodes:
                nodes.append({
                    "id": host_id,
                    "type": "host",
                    "mac": str(host.mac),
                    "ipv4": list(host.ipv4) if hasattr(host, "ipv4") else [],
                    "ipv6": list(host.ipv6) if hasattr(host, "ipv6") else []
                })
                seen_nodes.add(host_id)

            edges.append({
                "source": host_id,
                "target": switch_id,
                "type": "host-link",
                "port": int(host.port.port_no),
                "enabled": True
            })

        for link in self.app.links_inventory.values():
            src_iface = self.tc_service.get_interface_name(link["source"], link["src_port"])
            dst_iface = self.tc_service.get_interface_name(link["target"], link["dst_port"])

            src_tc = self.tc_service.get_interface_tc_state(src_iface)
            dst_tc = self.tc_service.get_interface_tc_state(dst_iface)

            edges.append({
                "source": link["source"],
                "target": link["target"],
                "type": "switch-link",
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": bool(link.get("enabled", False)),
                "discovered": bool(link.get("discovered", False)),
                "delay": src_tc["delay"] or dst_tc["delay"],
                "loss": src_tc["loss"] if src_tc["loss"] is not None else dst_tc["loss"],
                "bandwidth": src_tc["bandwidth"] or dst_tc["bandwidth"],
                "src_tc": src_tc,
                "dst_tc": dst_tc
            })

        return {
            "nodes": nodes,
            "edges": edges
        }