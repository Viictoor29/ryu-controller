import time
from ryu.topology.api import get_switch, get_link, get_host


class TopologyService:
    def __init__(self, app):
        self.app = app
        self.links_inventory = {}

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return tuple(sorted([a, b]))

    def normalize_endpoint(self, endpoint, name="endpoint"):
        if not isinstance(endpoint, dict):
            raise ValueError(f"{name} debe ser un objeto JSON")

        if "dpid" not in endpoint or "port_no" not in endpoint:
            raise ValueError(f"{name} debe incluir 'dpid' y 'port_no'")

        return {
            "dpid": str(endpoint["dpid"]),
            "port_no": int(endpoint["port_no"])
        }

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        No borra enlaces antiguos para poder seguir mostrando enlaces
        deshabilitados manualmente.
        """
        for key in list(self.links_inventory.keys()):
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
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        if key in self.links_inventory:
            self.links_inventory[key]["enabled"] = bool(enabled)
        else:
            self.links_inventory[key] = {
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

    def get_controller_status(self):
        """
        Endpoint ligero y seguro: no usa get_switch/get_link/get_host.
        """
        uptime_seconds = int(time.time() - self.app.start_time)

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.app.OFP_VERSIONS,
                "monitor_interval_seconds": self.app.stats_monitor.monitor_interval
            },
            "summary": {
                "switches_connected": len(self.app.datapaths),
                "port_stats_switches": len(self.app.stats_monitor.port_stats),
                "flow_stats_switches": len(self.app.stats_monitor.flow_stats),
                "links_inventory": len(self.links_inventory)
            }
        }

    def get_topology_data(self):
        nodes = []
        edges = []
        seen_nodes = set()

        # Switches conectados al controlador
        for dpid in sorted(self.app.datapaths.keys()):
            sw_id = str(dpid)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # Links descubiertos por Ryu
        try:
            links = get_link(self.app, None)
        except Exception as e:
            self.app.logger.exception("Error obteniendo links con get_link(): %s", e)
            links = []

        self.links_inventory = {}

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

        for link in self.links_inventory.values():
            edges.append({
                "source": link["source"],
                "target": link["target"],
                "type": "switch-link",
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "enabled": bool(link["enabled"]),
                "discovered": bool(link.get("discovered", False))
            })

        return {
            "nodes": nodes,
            "edges": edges
        }