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

    def _port_admin_state(self, dpid, port_no):
        return self.app.port_admin_state.get(str(dpid), {}).get(int(port_no), "up")

    def _port_stp_state(self, dpid, port_no):
        return self.app.stp_port_state.get(str(dpid), {}).get(int(port_no))

    def _port_effective_state(self, dpid, port_no, discovered=True, enabled=True):
        admin_state = self._port_admin_state(dpid, port_no)
        blocked = self.app.is_port_blocked(dpid, port_no)

        if not discovered or not enabled or admin_state == "down":
            return "down"
        if blocked:
            return "blocked_by_stp"
        return "up"

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        No borra enlaces antiguos para poder seguir mostrando enlaces caídos.
        """
        valid_keys = set()

        links = self.app.topology_get_links()

        for link in links:
            src_dpid = str(link.src.dpid)
            dst_dpid = str(link.dst.dpid)
            src_port = int(link.src.port_no)
            dst_port = int(link.dst.port_no)

            key = self.make_link_key(src_dpid, src_port, dst_dpid, dst_port)
            valid_keys.add(key)

            current = self.app.links_inventory.setdefault(key, {})
            current.update({
                "source": src_dpid,
                "target": dst_dpid,
                "src_port": src_port,
                "dst_port": dst_port,
                "enabled": True,
                "discovered": True,
            })

        for key in list(self.app.links_inventory.keys()):
            if key not in valid_keys:
                self.app.links_inventory[key]["enabled"] = False
                self.app.links_inventory[key]["discovered"] = False

    def set_link_inventory_state(self, src, dst, enabled):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        current = self.app.links_inventory.setdefault(key, {
            "source": src["dpid"],
            "target": dst["dpid"],
            "src_port": src["port_no"],
            "dst_port": dst["port_no"],
            "discovered": False
        })
        current["enabled"] = bool(enabled)

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
        self.app.port_admin_state.setdefault(dpid_str, {})
        self.app.port_admin_state[dpid_str][port_no] = "up" if up else "down"

        if not up:
            self.app.blocked_ports.discard((dpid, port_no))
            self.app.flush_switch_learning(datapath)

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

        for dpid in sorted(self.app.datapaths.keys()):
            sw_id = str(dpid)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": "S" + sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        try:
            hosts = self.app.topology_get_hosts()
        except Exception as e:
            self.app.logger.exception("Error obteniendo hosts con get_host(): %s", e)
            hosts = []

        for key in list(self.app.host_links_inventory.keys()):
            self.app.host_links_inventory[key]["discovered"] = False
            self.app.host_links_inventory[key]["enabled"] = False

        for host in hosts:
            host_id = str(host.mac)
            switch_id = str(host.port.dpid)
            switch_port = int(host.port.port_no)
            switch_iface = self.get_interface_name(switch_id, switch_port)
            switch_tc = self.get_interface_tc_state(switch_iface)

            host_link_key = (str(host.mac), str(switch_id), int(switch_port))

            self.app.host_links_inventory[host_link_key] = {
                "host_mac": str(host.mac),
                "switch": str(switch_id),
                "switch_port": int(switch_port),
                "enabled": True,
                "discovered": True
            }

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

            host_link_state = self.app.host_links_inventory.get(host_link_key, {})
            admin_state = self._port_admin_state(switch_id, switch_port)
            stp_state = self._port_stp_state(switch_id, switch_port)
            stp_blocked = self.app.is_port_blocked(switch_id, switch_port)
            discovered = bool(host_link_state.get("discovered", False))
            enabled = bool(host_link_state.get("enabled", False)) and admin_state == "up"
            effective_state = self._port_effective_state(
                switch_id,
                switch_port,
                discovered=discovered,
                enabled=enabled
            )

            edges.append({
                "type": "host-link",
                "source-h": "H" + h_id,
                "mac": str(host.mac),
                "target-s": "S" + switch_id,
                "s-port": switch_port,
                "s-iface": switch_iface,
                "enabled": enabled,
                "forwarding": effective_state == "up",
                "discovered": discovered,
                "state": effective_state,
                "admin_state": admin_state,
                "stp_state": stp_state,
                "stp_blocked": stp_blocked,
                "tc_sw_port": switch_tc,
                "degradation-link": port_status
            })

        for key, host_link in self.app.host_links_inventory.items():
            if host_link.get("discovered", False):
                continue

            host_mac = host_link["host_mac"]
            switch_id = host_link["switch"]
            switch_port = host_link["switch_port"]
            switch_iface = self.get_interface_name(switch_id, switch_port)

            host_num = self._host_number_from_mac(host_mac)
            h_id = host_num if host_num is not None else host_mac

            if host_mac not in seen_nodes:
                nodes.append({
                    "id": "H" + h_id,
                    "type": "host",
                    "mac": host_mac,
                    "ipv4": [],
                    "ipv6": []
                })
                seen_nodes.add(host_mac)

            edges.append({
                "type": "host-link",
                "source-h": "H" + h_id,
                "mac": host_mac,
                "target-s": "S" + switch_id,
                "s-port": switch_port,
                "s-iface": switch_iface,
                "enabled": False,
                "forwarding": False,
                "discovered": False,
                "state": "down",
                "admin_state": "down",
                "stp_state": None,
                "stp_blocked": False,
                "tc_sw_port": {
                    "delay": None,
                    "loss": None,
                    "bandwidth": None
                },
                "degradation-link": "healthy"
            })

        for link in self.app.links_inventory.values():
            if not link.get("discovered", False) and link.get("enabled", False):
                continue

            src_dpid = str(link["source"])
            dst_dpid = str(link["target"])
            src_port = int(link["src_port"])
            dst_port = int(link["dst_port"])

            src_iface = self.get_interface_name(src_dpid, src_port)
            dst_iface = self.get_interface_name(dst_dpid, dst_port)

            src_tc = self.get_interface_tc_state(src_iface)
            dst_tc = self.get_interface_tc_state(dst_iface)

            src_stats = self.app.port_stats.get(src_dpid, {}).get(src_port, {})
            dst_stats = self.app.port_stats.get(dst_dpid, {}).get(dst_port, {})

            src_degradation = self.compute_port_status(src_stats)
            dst_degradation = self.compute_port_status(dst_stats)
            link_degradation = self._combine_link_degradation(src_degradation, dst_degradation)

            src_admin = self._port_admin_state(src_dpid, src_port)
            dst_admin = self._port_admin_state(dst_dpid, dst_port)
            src_stp_state = self._port_stp_state(src_dpid, src_port)
            dst_stp_state = self._port_stp_state(dst_dpid, dst_port)
            src_blocked = self.app.is_port_blocked(src_dpid, src_port)
            dst_blocked = self.app.is_port_blocked(dst_dpid, dst_port)

            discovered = bool(link.get("discovered", False))
            inventory_enabled = bool(link.get("enabled", False))
            physical_up = (
                discovered
                and inventory_enabled
                and src_admin == "up"
                and dst_admin == "up"
            )
            forwarding = physical_up and not src_blocked and not dst_blocked

            if not physical_up:
                state = "down"
            elif not forwarding:
                state = "blocked_by_stp"
            else:
                state = "up"

            edges.append({
                "type": "switch-link",
                "source": "S" + src_dpid,
                "target": "S" + dst_dpid,
                "src_port": src_port,
                "dst_port": dst_port,
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": physical_up,
                "forwarding": forwarding,
                "discovered": discovered,
                "state": state,
                "admin_state": {
                    "src": src_admin,
                    "dst": dst_admin
                },
                "stp": {
                    "src_state": src_stp_state,
                    "dst_state": dst_stp_state,
                    "src_blocked": src_blocked,
                    "dst_blocked": dst_blocked
                },
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
