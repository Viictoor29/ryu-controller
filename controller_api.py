from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from ryu.lib import hub
from webob import Response
from ryu.topology.api import get_switch, get_link, get_host
import json
import subprocess
import re
import time


API_INSTANCE_NAME = "sdn_api_app"


class SDNControllerAPI(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "wsgi": WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        super(SDNControllerAPI, self).__init__(*args, **kwargs)

        wsgi = kwargs["wsgi"]
        wsgi.register(SDNRestController, {
            API_INSTANCE_NAME: self
        })

        self.datapaths = {}
        self.links_inventory = {}
        self.start_time = time.time()

        self.port_stats = {}
        self.port_speed = {}
        self.flow_stats = {}

        self.monitor_interval = 5
        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if datapath is None:
            return

        dpid = int(datapath.id)

        if ev.state == MAIN_DISPATCHER:
            if dpid not in self.datapaths:
                self.datapaths[dpid] = datapath
                self.logger.info("Switch conectado: %s", dpid)

        elif ev.state == DEAD_DISPATCHER:
            if dpid in self.datapaths:
                del self.datapaths[dpid]
                self.logger.info("Switch desconectado: %s", dpid)

    def _monitor(self):
        while True:
            for datapath in list(self.datapaths.values()):
                self._request_stats(datapath)
            hub.sleep(self.monitor_interval)

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        try:
            req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
            datapath.send_msg(req)

            req = parser.OFPFlowStatsRequest(datapath)
            datapath.send_msg(req)
        except Exception as e:
            self.logger.error("Error solicitando stats al switch %s: %s", datapath.id, e)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dpid = str(ev.msg.datapath.id)
        now = time.time()

        if dpid not in self.port_stats:
            self.port_stats[dpid] = {}

        if dpid not in self.port_speed:
            self.port_speed[dpid] = {}

        for stat in ev.msg.body:
            port_no = int(stat.port_no)

            if port_no > 0x7fffffff:
                continue

            prev = self.port_stats[dpid].get(port_no)

            current = {
                "port_no": port_no,
                "rx_packets": stat.rx_packets,
                "tx_packets": stat.tx_packets,
                "rx_bytes": stat.rx_bytes,
                "tx_bytes": stat.tx_bytes,
                "rx_dropped": stat.rx_dropped,
                "tx_dropped": stat.tx_dropped,
                "rx_errors": stat.rx_errors,
                "tx_errors": stat.tx_errors,
                "rx_frame_err": getattr(stat, "rx_frame_err", 0),
                "rx_over_err": getattr(stat, "rx_over_err", 0),
                "rx_crc_err": getattr(stat, "rx_crc_err", 0),
                "collisions": getattr(stat, "collisions", 0),
                "duration_sec": stat.duration_sec,
                "duration_nsec": getattr(stat, "duration_nsec", 0),
                "timestamp": now
            }

            self.port_stats[dpid][port_no] = current

            if prev:
                prev_total_bytes = prev["rx_bytes"] + prev["tx_bytes"]
                current_total_bytes = current["rx_bytes"] + current["tx_bytes"]
                delta_bytes = current_total_bytes - prev_total_bytes
                delta_time = now - prev["timestamp"]

                bps = (delta_bytes * 8 / delta_time) if delta_time > 0 else 0
                self.port_speed[dpid][port_no] = {
                    "bps": round(bps, 2),
                    "kbps": round(bps / 1_000, 3),
                    "mbps": round(bps / 1_000_000, 6)
                }
            else:
                self.port_speed[dpid][port_no] = {
                    "bps": 0,
                    "kbps": 0,
                    "mbps": 0
                }

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        dpid = str(ev.msg.datapath.id)
        flows = []

        for stat in ev.msg.body:
            if getattr(stat, "priority", 0) == 0:
                continue

            try:
                match_data = dict(stat.match.items())
            except Exception:
                match_data = str(stat.match)

            instructions = []
            try:
                for ins in getattr(stat, "instructions", []):
                    instructions.append(str(ins))
            except Exception:
                pass

            flows.append({
                "table_id": stat.table_id,
                "priority": stat.priority,
                "packet_count": stat.packet_count,
                "byte_count": stat.byte_count,
                "duration_sec": stat.duration_sec,
                "match": match_data,
                "instructions": instructions
            })

        self.flow_stats[dpid] = flows

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return tuple(sorted([a, b]))

    def sync_links_inventory(self):
        for key in self.links_inventory:
            self.links_inventory[key]["discovered"] = False

        links = get_link(self, None)

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

        datapath = self.datapaths.get(dpid)
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

    def get_interface_name(self, dpid, port_no):
        return f"s{int(dpid)}-eth{int(port_no)}"

    def run_command(self, cmd):
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
        except Exception as e:
            return 1, "", str(e)

    def get_interface_tc_state(self, iface):
        result = {
            "delay": None,
            "loss": None,
            "bandwidth": None
        }

        rc, qdisc_out, qdisc_err = self.run_command(["sudo", "tc", "qdisc", "show", "dev", iface])

        if rc == 0 and qdisc_out:
            delay_match = re.search(r"\bdelay\s+([0-9]+(?:\.[0-9]+)?[a-zA-Z]+)", qdisc_out)
            if delay_match:
                result["delay"] = delay_match.group(1)

            loss_match = re.search(r"\bloss\s+([0-9]+(?:\.[0-9]+)?)\s*%", qdisc_out)
            if loss_match:
                try:
                    result["loss"] = float(loss_match.group(1))
                except ValueError:
                    result["loss"] = loss_match.group(1)

            bw_match_qdisc = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", qdisc_out)
            if bw_match_qdisc:
                result["bandwidth"] = bw_match_qdisc.group(1)

        rc, class_out, class_err = self.run_command(["sudo", "tc", "class", "show", "dev", iface])

        if rc == 0 and class_out:
            bw_match_class = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", class_out)
            if bw_match_class:
                result["bandwidth"] = bw_match_class.group(1)

        return result

    def get_port_health(self, dpid, port_no):
        dpid = str(dpid)
        port_no = int(port_no)

        stats = self.port_stats.get(dpid, {}).get(port_no, {})
        speed = self.port_speed.get(dpid, {}).get(port_no, {
            "bps": 0,
            "kbps": 0,
            "mbps": 0
        })

        total_errors = stats.get("rx_errors", 0) + stats.get("tx_errors", 0)
        total_drops = stats.get("rx_dropped", 0) + stats.get("tx_dropped", 0)

        if total_errors > 0:
            status = "degraded"
        elif total_drops > 0:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
            "stats": stats,
            "speed": speed
        }

    def get_topology_data(self):
        self.sync_links_inventory()

        switches = get_switch(self, None)
        hosts = get_host(self, None)

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
            src_iface = self.get_interface_name(link["source"], link["src_port"])
            dst_iface = self.get_interface_name(link["target"], link["dst_port"])

            src_tc = self.get_interface_tc_state(src_iface)
            dst_tc = self.get_interface_tc_state(dst_iface)

            src_health = self.get_port_health(link["source"], link["src_port"])
            dst_health = self.get_port_health(link["target"], link["dst_port"])

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

    def normalize_bandwidth(self, value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}mbit"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(kbit|mbit|gbit)$", value):
            return value

        raise ValueError("Formato de bandwidth inválido. Usa por ejemplo: 10mbit, 100kbit, 1gbit")

    def normalize_delay(self, value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}ms"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(ms|s|us)$", value):
            return value

        raise ValueError("Formato de delay inválido. Usa por ejemplo: 100ms, 1s, 500us")

    def normalize_loss(self, value):
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            raise ValueError("Formato de loss inválido. Usa un número, por ejemplo: 5 o 0.5")

        if value < 0 or value > 100:
            raise ValueError("loss debe estar entre 0 y 100")

        return value

    def clear_interface_tc(self, iface):
        self.run_command(["sudo", "tc", "qdisc", "del", "dev", iface, "root"])

    def set_interface_tc(self, iface, delay=None, loss=None, bandwidth=None):
        delay = self.normalize_delay(delay) if delay is not None else None
        loss = self.normalize_loss(loss) if loss is not None else None
        bandwidth = self.normalize_bandwidth(bandwidth) if bandwidth is not None else None

        args = ["sudo", "tc", "qdisc", "replace", "dev", iface, "root", "netem"]

        has_any = False

        if delay is not None:
            args += ["delay", delay]
            has_any = True

        if loss is not None:
            args += ["loss", f"{loss}%"]
            has_any = True

        if bandwidth is not None:
            args += ["rate", bandwidth]
            has_any = True

        if not has_any:
            self.clear_interface_tc(iface)
            return {
                "iface": iface,
                "delay": None,
                "loss": None,
                "bandwidth": None
            }

        rc, out, err = self.run_command(args)
        if rc != 0:
            raise RuntimeError(f"Error aplicando tc en {iface}: {err or out}")

        state = self.get_interface_tc_state(iface)
        return {
            "iface": iface,
            "delay": state["delay"],
            "loss": state["loss"],
            "bandwidth": state["bandwidth"]
        }

    def update_link_tc(self, src, dst, delay=None, loss=None, bandwidth=None):
        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_result = self.set_interface_tc(
            src_iface,
            delay=delay,
            loss=loss,
            bandwidth=bandwidth
        )

        dst_result = self.set_interface_tc(
            dst_iface,
            delay=delay,
            loss=loss,
            bandwidth=bandwidth
        )

        return {
            "src": {
                "dpid": str(src["dpid"]),
                "port_no": int(src["port_no"]),
                **src_result
            },
            "dst": {
                "dpid": str(dst["dpid"]),
                "port_no": int(dst["port_no"]),
                **dst_result
            }
        }

    def set_link_loss(self, src, dst, loss):
        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(
            src, dst,
            delay=current_delay,
            loss=loss,
            bandwidth=current_bw
        )
        result["link_state"] = "loss_updated"
        return result

    def set_link_delay(self, src, dst, delay):
        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(
            src, dst,
            delay=delay,
            loss=current_loss,
            bandwidth=current_bw
        )
        result["link_state"] = "delay_updated"
        return result

    def set_link_bandwidth(self, src, dst, bandwidth):
        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]

        result = self.update_link_tc(
            src, dst,
            delay=current_delay,
            loss=current_loss,
            bandwidth=bandwidth
        )
        result["link_state"] = "bandwidth_updated"
        return result

    def clear_link_tc(self, src, dst):
        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        self.clear_interface_tc(src_iface)
        self.clear_interface_tc(dst_iface)

        return {
            "src": {
                "dpid": str(src["dpid"]),
                "port_no": int(src["port_no"]),
                "iface": src_iface
            },
            "dst": {
                "dpid": str(dst["dpid"]),
                "port_no": int(dst["port_no"]),
                "iface": dst_iface
            },
            "link_state": "tc_cleared"
        }

    def get_controller_status(self):
        self.sync_links_inventory()

        switches = get_switch(self, None)
        hosts = get_host(self, None)

        uptime_seconds = int(time.time() - self.start_time)
        active_links = [l for l in self.links_inventory.values() if l.get("enabled", False)]
        discovered_links = [l for l in self.links_inventory.values() if l.get("discovered", False)]

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.OFP_VERSIONS,
                "monitor_interval_seconds": self.monitor_interval
            },
            "summary": {
                "switches": len(switches),
                "switches_connected": len(self.datapaths),
                "hosts": len(hosts),
                "links_total_inventory": len(self.links_inventory),
                "links_discovered": len(discovered_links),
                "links_enabled": len(active_links)
            }
        }

    def get_health_metrics(self):
        self.sync_links_inventory()

        switches_health = []

        for dpid in sorted(self.datapaths.keys()):
            dpid_str = str(dpid)

            ports = []
            dpid_port_stats = self.port_stats.get(dpid_str, {})
            dpid_port_speed = self.port_speed.get(dpid_str, {})
            dpid_flows = self.flow_stats.get(dpid_str, [])

            total_rx_errors = 0
            total_tx_errors = 0
            total_rx_dropped = 0
            total_tx_dropped = 0
            total_bps = 0

            for port_no in sorted(dpid_port_stats.keys()):
                stats = dpid_port_stats.get(port_no, {})
                speed = dpid_port_speed.get(port_no, {
                    "bps": 0,
                    "kbps": 0,
                    "mbps": 0
                })

                total_rx_errors += stats.get("rx_errors", 0)
                total_tx_errors += stats.get("tx_errors", 0)
                total_rx_dropped += stats.get("rx_dropped", 0)
                total_tx_dropped += stats.get("tx_dropped", 0)
                total_bps += speed.get("bps", 0)

                port_status = "healthy"
                if stats.get("rx_errors", 0) + stats.get("tx_errors", 0) > 0:
                    port_status = "degraded"
                elif stats.get("rx_dropped", 0) + stats.get("tx_dropped", 0) > 0:
                    port_status = "warning"

                ports.append({
                    "port_no": port_no,
                    "status": port_status,
                    "stats": stats,
                    "speed": speed
                })

            switch_status = "healthy"
            if (total_rx_errors + total_tx_errors) > 0:
                switch_status = "degraded"
            elif (total_rx_dropped + total_tx_dropped) > 0:
                switch_status = "warning"

            switches_health.append({
                "dpid": dpid_str,
                "connected": True,
                "status": switch_status,
                "ports": ports,
                "flow_count": len(dpid_flows),
                "flows": dpid_flows,
                "traffic": {
                    "bps": round(total_bps, 2),
                    "kbps": round(total_bps / 1000, 3),
                    "mbps": round(total_bps / 1000000, 6)
                },
                "totals": {
                    "rx_errors": total_rx_errors,
                    "tx_errors": total_tx_errors,
                    "rx_dropped": total_rx_dropped,
                    "tx_dropped": total_tx_dropped
                }
            })

        return {
            "timestamp": int(time.time()),
            "controller_uptime_seconds": int(time.time() - self.start_time),
            "switch_count": len(self.datapaths),
            "switches": switches_health
        }

    def get_health_summary(self):
        health = self.get_health_metrics()

        healthy_switches = 0
        warning_switches = 0
        degraded_switches = 0

        healthy_ports = 0
        warning_ports = 0
        degraded_ports = 0

        total_flows = 0
        total_bps = 0

        for sw in health["switches"]:
            total_flows += sw.get("flow_count", 0)
            total_bps += sw.get("traffic", {}).get("bps", 0)

            if sw["status"] == "healthy":
                healthy_switches += 1
            elif sw["status"] == "warning":
                warning_switches += 1
            elif sw["status"] == "degraded":
                degraded_switches += 1

            for port in sw.get("ports", []):
                if port["status"] == "healthy":
                    healthy_ports += 1
                elif port["status"] == "warning":
                    warning_ports += 1
                elif port["status"] == "degraded":
                    degraded_ports += 1

        links_total = len(self.links_inventory)
        links_enabled = len([l for l in self.links_inventory.values() if l.get("enabled", False)])
        links_discovered = len([l for l in self.links_inventory.values() if l.get("discovered", False)])

        return {
            "timestamp": int(time.time()),
            "controller_uptime_seconds": int(time.time() - self.start_time),
            "switches": {
                "total": health["switch_count"],
                "healthy": healthy_switches,
                "warning": warning_switches,
                "degraded": degraded_switches
            },
            "ports": {
                "healthy": healthy_ports,
                "warning": warning_ports,
                "degraded": degraded_ports
            },
            "links": {
                "total_inventory": links_total,
                "enabled": links_enabled,
                "discovered": links_discovered
            },
            "flows": {
                "total": total_flows
            },
            "traffic": {
                "bps": round(total_bps, 2),
                "kbps": round(total_bps / 1000, 3),
                "mbps": round(total_bps / 1000000, 6)
            },
            "overall_status": self.compute_overall_status(
                degraded_switches, warning_switches, degraded_ports, warning_ports
            )
        }

    def compute_overall_status(self, degraded_switches, warning_switches, degraded_ports, warning_ports):
        if degraded_switches > 0 or degraded_ports > 0:
            return "degraded"
        if warning_switches > 0 or warning_ports > 0:
            return "warning"
        return "healthy"

    def get_switch_ports(self, dpid):
        dpid = str(dpid)

        if dpid not in self.port_stats:
            return {
                "dpid": dpid,
                "ports": []
            }

        ports = []
        for port_no in sorted(self.port_stats[dpid].keys()):
            ports.append({
                "port_no": port_no,
                "health": self.get_port_health(dpid, port_no)
            })

        return {
            "dpid": dpid,
            "ports": ports
        }

    def get_switch_flows(self, dpid):
        dpid = str(dpid)
        return {
            "dpid": dpid,
            "flow_count": len(self.flow_stats.get(dpid, [])),
            "flows": self.flow_stats.get(dpid, [])
        }


class SDNRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SDNRestController, self).__init__(req, link, data, **config)
        self.sdn_app = data[API_INSTANCE_NAME]

    def json_response(self, data, status=200):
        return Response(
            status=status,
            content_type="application/json",
            charset="utf-8",
            body=json.dumps(data).encode("utf-8"),
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, Accept")
            ]
        )

    def cors_preflight(self):
        return Response(
            status=200,
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, Accept"),
                ("Content-Length", "0")
            ]
        )

    def read_json_body(self, req):
        if not req.body:
            return {}
        return json.loads(req.body.decode("utf-8"))

    @route("topology", "/api/topology", methods=["GET", "OPTIONS"])
    def get_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_topology_data()
            return self.json_response(body)
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("disable_link", "/api/links/disable", methods=["POST", "OPTIONS"])
    def disable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.disable_link(body["src"], body["dst"])

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("enable_link", "/api/links/enable", methods=["POST", "OPTIONS"])
    def enable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.enable_link(body["src"], body["dst"])

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("set_link_loss", "/api/links/loss", methods=["POST", "OPTIONS"])
    def set_link_loss(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.set_link_loss(
                body["src"],
                body["dst"],
                body["loss"]
            )

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("set_link_bandwidth", "/api/links/bandwidth", methods=["POST", "OPTIONS"])
    def set_link_bandwidth(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.set_link_bandwidth(
                body["src"],
                body["dst"],
                body["bandwidth"]
            )

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("set_link_delay", "/api/links/delay", methods=["POST", "OPTIONS"])
    def set_link_delay(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.set_link_delay(
                body["src"],
                body["dst"],
                body["delay"]
            )

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("clear_link_tc", "/api/links/tc/clear", methods=["POST", "OPTIONS"])
    def clear_link_tc(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            result = self.sdn_app.clear_link_tc(
                body["src"],
                body["dst"]
            )

            return self.json_response({
                "ok": True,
                "data": result
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=400)

    @route("controller_status", "/api/controller/status", methods=["GET", "OPTIONS"])
    def get_controller_status(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_controller_status()
            return self.json_response({
                "ok": True,
                "data": body
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("health_metrics", "/api/health", methods=["GET", "OPTIONS"])
    def get_health_metrics(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_health_metrics()
            return self.json_response({
                "ok": True,
                "data": body
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("health_summary", "/api/health/summary", methods=["GET", "OPTIONS"])
    def get_health_summary(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_health_summary()
            return self.json_response({
                "ok": True,
                "data": body
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("switch_ports", "/api/switch/{dpid}/ports", methods=["GET", "OPTIONS"])
    def get_switch_ports(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.get_switch_ports(dpid)
            return self.json_response({
                "ok": True,
                "data": body
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("switch_flows", "/api/switch/{dpid}/flows", methods=["GET", "OPTIONS"])
    def get_switch_flows(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.get_switch_flows(dpid)
            return self.json_response({
                "ok": True,
                "data": body
            })
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)