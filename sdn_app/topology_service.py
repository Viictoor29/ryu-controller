from ryu.topology.api import get_switch, get_link, get_host


class TopologyService:
    def __init__(self, app):
        self.app = app
        self.links_inventory = {}

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return tuple(sorted([a, b]))

    def sync_links_inventory(self):
        for key in self.links_inventory:
            self.links_inventory[key]["discovered"] = False

        links = get_link(self.app, None)

        for link in links:
            src_dpid = str(link.src.dpid)
            dst_dpid = str(link.dst.dpid)
            src_port = int(link.src.port_no)
            dst_port = int(link.dst.port_no)

            key = self.make_link_key(src_dpid, src_port, dst_dpid, dst_port)

            if key not in self.links_inventory:
                self.links_inventory[key] = {
                    "source": src_dpid,
                    "target": dst_dpid,
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "enabled": True,
                    "discovered": True
                }
            else:
                self.links_inventory[key]["enabled"] = True
                self.links_inventory[key]["discovered"] = True

    def set_link_inventory_state(self, src, dst, enabled):
        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        if key in self.links_inventory:
            self.links_inventory[key]["enabled"] = enabled
        else:
            self.links_inventory[key] = {
                "source": str(src["dpid"]),
                "target": str(dst["dpid"]),
                "src_port": int(src["port_no"]),
                "dst_port": int(dst["port_no"]),
                "enabled": enabled,
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

        return {
            "dpid": str(dpid),
            "port_no": port_no,
            "state": "up" if up else "down"
        }

    def disable_link(self, src, dst):
        result_src = self.set_port_state(src["dpid"], src["port_no"], up=False)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=False)

        self.set_link_inventory_state(src, dst, enabled=False)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "disabled"
        }

    def enable_link(self, src, dst):
        result_src = self.set_port_state(src["dpid"], src["port_no"], up=True)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=True)

        self.set_link_inventory_state(src, dst, enabled=True)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "enabled"
        }

    def get_controller_status(self):
        self.sync_links_inventory()

        switches = get_switch(self.app, None)
        hosts = get_host(self.app, None)

        uptime_seconds = int(__import__("time").time() - self.app.start_time)
        active_links = [l for l in self.links_inventory.values() if l.get("enabled", False)]
        discovered_links = [l for l in self.links_inventory.values() if l.get("discovered", False)]

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.app.OFP_VERSIONS,
                "monitor_interval_seconds": self.app.stats_monitor.monitor_interval
            },
            "summary": {
                "switches": len(switches),
                "switches_connected": len(self.app.datapaths),
                "hosts": len(hosts),
                "links_total_inventory": len(self.links_inventory),
                "links_discovered": len(discovered_links),
                "links_enabled": len(active_links)
            }
        }

    def get_topology_data(self):
        self.sync_links_inventory()

        switches = get_switch(self.app, None)
        hosts = get_host(self.app, None)

        nodes = []
        edges = []
        seen_nodes = set()

        for sw in switches:
            sw_id = str(sw.dp.id)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

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

        for link in self.links_inventory.values():
            src_iface = self.app.tc_manager.get_interface_name(link["source"], link["src_port"])
            dst_iface = self.app.tc_manager.get_interface_name(link["target"], link["dst_port"])

            src_tc = self.app.tc_manager.get_interface_tc_state(src_iface)
            dst_tc = self.app.tc_manager.get_interface_tc_state(dst_iface)

            src_health = self.app.health_service.get_port_health(link["source"], link["src_port"])
            dst_health = self.app.health_service.get_port_health(link["target"], link["dst_port"])

            edges.append({
                "source": link["source"],
                "target": link["target"],
                "type": "switch-link",
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": bool(link["enabled"]),
                "discovered": bool(link.get("discovered", False)),
                "configured_delay": src_tc["delay"],
                "configured_loss": src_tc["loss"],
                "configured_bandwidth": src_tc["bandwidth"],
                "src_tc_state": src_tc,
                "dst_tc_state": dst_tc,
                "src_port_health": src_health,
                "dst_port_health": dst_health
            })

        return {
            "nodes": nodes,
            "edges": edges
        }