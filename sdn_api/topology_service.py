from rest_helpers import (
    make_link_key,
    normalize_endpoint,
    get_interface_name,
    get_interface_tc_state,
    compute_port_status,
)


class TopologyService:
    def __init__(self, app):
        self.app = app

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        return make_link_key(src_dpid, src_port, dst_dpid, dst_port)

    def normalize_endpoint(self, endpoint, name="endpoint"):
        return normalize_endpoint(endpoint, name)

    def get_interface_name(self, dpid, port_no):
        return get_interface_name(dpid, port_no)

    def get_interface_tc_state(self, iface):
        return get_interface_tc_state(iface)

    def compute_port_status(self, stats):
        return compute_port_status(stats)

    def _combine_link_degradation(self, src_status, dst_status):
        if "degraded" in (src_status, dst_status):
            return "degraded"
        if "warning" in (src_status, dst_status):
            return "warning"
        return "healthy"

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        No borra enlaces antiguos para poder seguir mostrando enlaces
        deshabilitados manualmente.
        """
        for key in list(self.app.links_inventory.keys()):
            self.app.links_inventory[key]["discovered"] = False

        links = self.app.topology_get_links()

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
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

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

    def set_port_state(self, dpid, port_no, up=True):
        dpid = int(dpid)
        port_no = int(port_no)

        datapath = self.app.datapaths.get(dpid)
        if datapath is None:
            raise ValueError(f"No se encontró el switch {dpid}")

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        port = getattr(datapath, "ports", {}).get(port_no)
        if port is None:
            raise ValueError(f"No se encontró el puerto {port_no} en el switch {dpid}")

        config = 0 if up else ofproto.OFPPC_PORT_DOWN
        mask = ofproto.OFPPC_PORT_DOWN

        msg = parser.OFPPortMod(
            datapath=datapath,
            port_no=port_no,
            hw_addr=port.hw_addr,
            config=config,
            mask=mask,
            advertise=0
        )
        datapath.send_msg(msg)

        dpid_str = str(dpid)
        if dpid_str not in self.app.port_admin_state:
            self.app.port_admin_state[dpid_str] = {}

        self.app.port_admin_state[dpid_str][port_no] = "up" if up else "down"

        return {
            "dpid": str(dpid),
            "port_no": port_no,
            "state": "up" if up else "down"
        }

    def disable_link(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=False)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=False)

        self.set_link_inventory_state(src, dst, enabled=False)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "disabled"
        }

    def enable_link(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=True)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=True)

        self.set_link_inventory_state(src, dst, enabled=True)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "enabled"
        }

    def _host_number_from_mac(self, mac):
        mac = str(mac).strip().lower()
        parts = mac.split(":")
        if len(parts) != 6:
            return None

        try:
            return str(int(parts[-1], 16))
        except ValueError:
            return None
    
    def _host_name_from_mac(self, mac):
        num = self._host_number_from_mac(mac)
        return f"h{num}" if num is not None else None

    def get_topology_data(self):
        self.sync_links_inventory()

        nodes = []
        edges = []
        seen_nodes = set()

        # Switches descubiertos / conectados
        try:
            switches = self.app.topology_get_switches()
        except Exception as e:
            self.app.logger.exception("Error obteniendo switches con get_switch(): %s", e)
            switches = []

        for sw in switches:
            sw_id = str(sw.dp.id)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": "S" + sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # Fallback: switches conectados al controlador aunque get_switch falle
        for dpid in sorted(self.app.datapaths.keys()):
            sw_id = str(dpid)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": "S" + sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # Hosts descubiertos por Ryu
        try:
            hosts = self.app.topology_get_hosts()
        except Exception as e:
            self.app.logger.exception("Error obteniendo hosts con get_host(): %s", e)
            hosts = []

        for host in hosts:
            host_id = str(host.mac)
            switch_id = str(host.port.dpid)
            switch_port = int(host.port.port_no)
            switch_iface = self.get_interface_name(switch_id, switch_port)
            switch_tc = self.get_interface_tc_state(switch_iface)

            port_stats = self.app.port_stats.get(switch_id, {}).get(switch_port, {})
            port_status = self.compute_port_status(port_stats)

            host_num = self._host_number_from_mac(host.mac)
            h_id = host_num if host_num is not None else str(host.mac)

            if host_id not in seen_nodes:
                nodes.append({
                    "id": "H" + h_id,
                    "type": "host",
                    "mac": str(host.mac),
                    "ipv4": list(host.ipv4) if hasattr(host, "ipv4") else [],
                    "ipv6": list(host.ipv6) if hasattr(host, "ipv6") else []
                })
                seen_nodes.add(host_id)

            admin_state = self.app.port_admin_state.get(switch_id, {}).get(switch_port, "up")
            enabled = admin_state == "up"

            edges.append({
                "type": "host-link",
                "source-h": "H" + h_id,
                "mac": str(host.mac),
                "target-s": "S" + switch_id,
                "s-port": switch_port,
                "s-iface": switch_iface,
                "enabled": enabled,
                "admin_state": admin_state,
                "tc_sw_port": switch_tc,
                "degradation-link": port_status
            })

        # Links entre switches + estado tc + degradación
        for link in self.app.links_inventory.values():
            src_iface = self.get_interface_name(link["source"], link["src_port"])
            dst_iface = self.get_interface_name(link["target"], link["dst_port"])

            src_tc = self.get_interface_tc_state(src_iface)
            dst_tc = self.get_interface_tc_state(dst_iface)

            src_stats = self.app.port_stats.get(str(link["source"]), {}).get(int(link["src_port"]), {})
            dst_stats = self.app.port_stats.get(str(link["target"]), {}).get(int(link["dst_port"]), {})

            src_degradation = self.compute_port_status(src_stats)
            dst_degradation = self.compute_port_status(dst_stats)
            link_degradation = self._combine_link_degradation(src_degradation, dst_degradation)

            edges.append({
                "type": "switch-link",
                "source": "S" + link["source"],
                "target": "S" + link["target"],
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": bool(link.get("enabled", False)),
                "discovered": bool(link.get("discovered", False)),
                "src_tc": src_tc,
                "dst_tc": dst_tc,
                "src_degradation": src_degradation,
                "dst_degradation": dst_degradation,
                "degradation-link": link_degradation
            })

        return {
            "nodes": nodes,
            "edges": edges
        }