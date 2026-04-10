from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from ryu.lib import hub
from ryu.topology.api import get_switch, get_link, get_host
from webob import Response

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
        wsgi.register(SDNRestController, {API_INSTANCE_NAME: self})

        self.start_time = time.time()
        self.datapaths = {}
        self.links_inventory = {}

        # Estadísticas y monitorización
        self.port_stats = {}
        self.port_speed = {}
        self.flow_stats = {}
        self.monitor_interval = 5
        self.monitor_thread = hub.spawn(self._monitor)

        self.logger.info("SDNControllerAPI iniciada correctamente")

    # =========================================================
    # EVENTOS / DATAPATHS
    # =========================================================

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
            else:
                self.datapaths[dpid] = datapath

        elif ev.state == DEAD_DISPATCHER:
            if dpid in self.datapaths:
                del self.datapaths[dpid]
                self.logger.info("Switch desconectado: %s", dpid)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        try:
            self.handle_port_stats_reply(ev)
        except Exception as e:
            self.logger.exception("Error procesando EventOFPPortStatsReply: %s", e)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        try:
            self.handle_flow_stats_reply(ev)
        except Exception as e:
            self.logger.exception("Error procesando EventOFPFlowStatsReply: %s", e)

    # =========================================================
    # HELPERS GENERALES
    # =========================================================

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

    def _empty_speed(self):
        return {
            "bps": 0,
            "kbps": 0,
            "mbps": 0
        }

    # =========================================================
    # TOPOLOGÍA
    # =========================================================

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        No borra enlaces antiguos para poder seguir mostrando enlaces
        deshabilitados manualmente.
        """
        for key in list(self.links_inventory.keys()):
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

    def get_topology_data(self):
        self.sync_links_inventory()

        nodes = []
        edges = []
        seen_nodes = set()

        # Switches descubiertos / conectados
        try:
            switches = get_switch(self, None)
        except Exception as e:
            self.logger.exception("Error obteniendo switches con get_switch(): %s", e)
            switches = []

        for sw in switches:
            sw_id = str(sw.dp.id)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # Fallback: switches conectados al controlador aunque get_switch falle
        for dpid in sorted(self.datapaths.keys()):
            sw_id = str(dpid)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # Hosts descubiertos por Ryu
        try:
            hosts = get_host(self, None)
        except Exception as e:
            self.logger.exception("Error obteniendo hosts con get_host(): %s", e)
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

        # Links entre switches + estado tc
        for link in self.links_inventory.values():
            src_iface = self.get_interface_name(link["source"], link["src_port"])
            dst_iface = self.get_interface_name(link["target"], link["dst_port"])

            src_tc = self.get_interface_tc_state(src_iface)
            dst_tc = self.get_interface_tc_state(dst_iface)

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

    # =========================================================
    # TC / NETEM
    # =========================================================

    def get_interface_name(self, dpid, port_no):
        return f"s{int(dpid)}-eth{int(port_no)}"

    def run_command(self, cmd, timeout=5):
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout
            )
            return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
        except subprocess.TimeoutExpired:
            return 1, "", f"Timeout ejecutando comando: {' '.join(cmd)}"
        except Exception as e:
            return 1, "", str(e)

    def get_interface_tc_state(self, iface):
        result = {
            "delay": None,
            "loss": None,
            "bandwidth": None
        }

        rc, qdisc_out, _ = self.run_command(["sudo", "tc", "qdisc", "show", "dev", iface])

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

        rc, class_out, _ = self.run_command(["sudo", "tc", "class", "show", "dev", iface])

        if rc == 0 and class_out:
            bw_match_class = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", class_out)
            if bw_match_class:
                result["bandwidth"] = bw_match_class.group(1)

        return result

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
        rc, out, err = self.run_command(["sudo", "tc", "qdisc", "del", "dev", iface, "root"])

        if rc != 0:
            error_text = (err or out).lower()
            if "no such file" in error_text or "cannot find device" in error_text:
                raise RuntimeError(f"La interfaz {iface} no existe")
            if "noqueue" in error_text or "no qdisc" in error_text or "not found" in error_text:
                return
            if "operation not permitted" in error_text or "permission denied" in error_text:
                raise RuntimeError(
                    f"No hay permisos para ejecutar tc sobre {iface}. "
                    f"Configura sudo sin password para el comando tc."
                )

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
            error_text = err or out

            if "operation not permitted" in error_text.lower() or "permission denied" in error_text.lower():
                raise RuntimeError(
                    f"No hay permisos para ejecutar tc sobre {iface}. "
                    f"Configura sudo sin password para el comando tc."
                )

            if "cannot find device" in error_text.lower() or "no such file" in error_text.lower():
                raise RuntimeError(f"La interfaz {iface} no existe")

            raise RuntimeError(f"Error aplicando tc en {iface}: {error_text}")

        state = self.get_interface_tc_state(iface)
        return {
            "iface": iface,
            "delay": state["delay"],
            "loss": state["loss"],
            "bandwidth": state["bandwidth"]
        }

    def update_link_tc(self, src, dst, delay=None, loss=None, bandwidth=None):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_result = self.set_interface_tc(src_iface, delay=delay, loss=loss, bandwidth=bandwidth)
        dst_result = self.set_interface_tc(dst_iface, delay=delay, loss=loss, bandwidth=bandwidth)

        return {
            "src": {
                "dpid": src["dpid"],
                "port_no": src["port_no"],
                **src_result
            },
            "dst": {
                "dpid": dst["dpid"],
                "port_no": dst["port_no"],
                **dst_result
            }
        }

    def set_link_loss(self, src, dst, loss):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(src, dst, delay=current_delay, loss=loss, bandwidth=current_bw)
        result["link_state"] = "loss_updated"
        return result

    def set_link_delay(self, src, dst, delay):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(src, dst, delay=delay, loss=current_loss, bandwidth=current_bw)
        result["link_state"] = "delay_updated"
        return result

    def set_link_bandwidth(self, src, dst, bandwidth):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]

        result = self.update_link_tc(src, dst, delay=current_delay, loss=current_loss, bandwidth=bandwidth)
        result["link_state"] = "bandwidth_updated"
        return result

    def clear_link_tc(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        self.clear_interface_tc(src_iface)
        self.clear_interface_tc(dst_iface)

        return {
            "src": {
                "dpid": src["dpid"],
                "port_no": src["port_no"],
                "iface": src_iface
            },
            "dst": {
                "dpid": dst["dpid"],
                "port_no": dst["port_no"],
                "iface": dst_iface
            },
            "link_state": "tc_cleared"
        }

    # =========================================================
    # MONITOR DE ESTADÍSTICAS
    # =========================================================

    def _monitor(self):
        while True:
            try:
                datapaths = list(self.datapaths.values())
                for datapath in datapaths:
                    self._request_stats(datapath)
            except Exception as e:
                self.logger.exception("Error en el monitor de estadísticas: %s", e)

            hub.sleep(self.monitor_interval)

    def _request_stats(self, datapath):
        if datapath is None:
            return

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        try:
            port_req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
            datapath.send_msg(port_req)

            flow_req = parser.OFPFlowStatsRequest(datapath)
            datapath.send_msg(flow_req)
        except Exception as e:
            self.logger.error(
                "Error solicitando stats al switch %s: %s",
                getattr(datapath, "id", "unknown"),
                e
            )

    def handle_port_stats_reply(self, ev):
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
                prev_total_bytes = prev.get("rx_bytes", 0) + prev.get("tx_bytes", 0)
                current_total_bytes = current["rx_bytes"] + current["tx_bytes"]
                delta_bytes = current_total_bytes - prev_total_bytes
                delta_time = now - prev.get("timestamp", now)

                if delta_bytes < 0:
                    delta_bytes = 0

                bps = (delta_bytes * 8 / delta_time) if delta_time > 0 else 0

                self.port_speed[dpid][port_no] = {
                    "bps": round(bps, 2),
                    "kbps": round(bps / 1000, 3),
                    "mbps": round(bps / 1000000, 6)
                }
            else:
                self.port_speed[dpid][port_no] = self._empty_speed()

    def handle_flow_stats_reply(self, ev):
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
                instructions = []

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

    # =========================================================
    # HEALTH / ESTADO
    # =========================================================

    def _compute_port_status(self, stats):
        total_errors = stats.get("rx_errors", 0) + stats.get("tx_errors", 0)
        total_drops = stats.get("rx_dropped", 0) + stats.get("tx_dropped", 0)

        if total_errors > 0:
            return "degraded"
        if total_drops > 0:
            return "warning"
        return "healthy"

    def get_port_health(self, dpid, port_no):
        dpid = str(dpid)
        port_no = int(port_no)

        stats = self.port_stats.get(dpid, {}).get(port_no, {})
        speed = self.port_speed.get(dpid, {}).get(port_no, self._empty_speed())

        return {
            "status": self._compute_port_status(stats),
            "stats": stats,
            "speed": speed
        }

    def compute_overall_status(self, degraded_switches, warning_switches, degraded_ports, warning_ports):
        if degraded_switches > 0 or degraded_ports > 0:
            return "degraded"
        if warning_switches > 0 or warning_ports > 0:
            return "warning"
        return "healthy"

    def get_health_metrics(self):
        try:
            self.sync_links_inventory()
        except Exception as e:
            self.logger.exception("Error sincronizando inventario de enlaces: %s", e)

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
                speed = dpid_port_speed.get(port_no, self._empty_speed())

                total_rx_errors += stats.get("rx_errors", 0)
                total_tx_errors += stats.get("tx_errors", 0)
                total_rx_dropped += stats.get("rx_dropped", 0)
                total_tx_dropped += stats.get("tx_dropped", 0)
                total_bps += speed.get("bps", 0)

                ports.append({
                    "port_no": int(port_no),
                    "status": self._compute_port_status(stats),
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

        for sw in health.get("switches", []):
            total_flows += sw.get("flow_count", 0)
            total_bps += sw.get("traffic", {}).get("bps", 0)

            if sw.get("status") == "healthy":
                healthy_switches += 1
            elif sw.get("status") == "warning":
                warning_switches += 1
            elif sw.get("status") == "degraded":
                degraded_switches += 1

            for port in sw.get("ports", []):
                if port.get("status") == "healthy":
                    healthy_ports += 1
                elif port.get("status") == "warning":
                    warning_ports += 1
                elif port.get("status") == "degraded":
                    degraded_ports += 1

        links_inventory = self.links_inventory
        links_total = len(links_inventory)
        links_enabled = len([link for link in links_inventory.values() if link.get("enabled", False)])
        links_discovered = len([link for link in links_inventory.values() if link.get("discovered", False)])

        return {
            "timestamp": int(time.time()),
            "controller_uptime_seconds": int(time.time() - self.start_time),
            "switches": {
                "total": health.get("switch_count", 0),
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
                degraded_switches,
                warning_switches,
                degraded_ports,
                warning_ports
            )
        }

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
                "port_no": int(port_no),
                "health": self.get_port_health(dpid, port_no)
            })

        return {
            "dpid": dpid,
            "ports": ports
        }

    def get_switch_flows(self, dpid):
        dpid = str(dpid)
        flows = self.flow_stats.get(dpid, [])

        return {
            "dpid": dpid,
            "flow_count": len(flows),
            "flows": flows
        }

    def get_controller_status(self):
        uptime_seconds = int(time.time() - self.start_time)

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.OFP_VERSIONS,
                "monitor_interval_seconds": self.monitor_interval
            },
            "summary": {
                "switches_connected": len(self.datapaths),
                "port_stats_switches": len(self.port_stats),
                "flow_stats_switches": len(self.flow_stats),
                "links_inventory": len(self.links_inventory)
            }
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

    def error_response(self, error, status=400):
        return self.json_response({
            "ok": False,
            "error": str(error)
        }, status=status)

    def success_response(self, data, status=200):
        return self.json_response({
            "ok": True,
            "data": data
        }, status=status)

    def read_json_body(self, req):
        if not req.body:
            return {}

        try:
            return json.loads(req.body.decode("utf-8"))
        except Exception:
            raise ValueError("JSON inválido en el body de la petición")

    def require_fields(self, body, *fields):
        missing = [field for field in fields if field not in body]
        if missing:
            raise ValueError(f"Faltan campos obligatorios: {', '.join(missing)}")

    @route("topology", "/api/topology", methods=["GET", "OPTIONS"])
    def get_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_topology_data()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/topology: %s", e)
            return self.error_response(e, status=500)

    @route("disable_link", "/api/links/disable", methods=["POST", "OPTIONS"])
    def disable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.disable_link(body["src"], body["dst"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/disable: %s", e)
            return self.error_response(e, status=400)

    @route("enable_link", "/api/links/enable", methods=["POST", "OPTIONS"])
    def enable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.enable_link(body["src"], body["dst"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/enable: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_loss", "/api/links/loss", methods=["POST", "OPTIONS"])
    def set_link_loss(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "loss")

            result = self.sdn_app.set_link_loss(body["src"], body["dst"], body["loss"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/loss: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_bandwidth", "/api/links/bandwidth", methods=["POST", "OPTIONS"])
    def set_link_bandwidth(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "bandwidth")

            result = self.sdn_app.set_link_bandwidth(body["src"], body["dst"], body["bandwidth"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/bandwidth: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_delay", "/api/links/delay", methods=["POST", "OPTIONS"])
    def set_link_delay(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "delay")

            result = self.sdn_app.set_link_delay(body["src"], body["dst"], body["delay"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/delay: %s", e)
            return self.error_response(e, status=400)

    @route("clear_link_tc", "/api/links/tc/clear", methods=["POST", "OPTIONS"])
    def clear_link_tc(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.clear_link_tc(body["src"], body["dst"])
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/tc/clear: %s", e)
            return self.error_response(e, status=400)

    @route("controller_status", "/api/controller/status", methods=["GET", "OPTIONS"])
    def get_controller_status(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_controller_status()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/controller/status: %s", e)
            return self.error_response(e, status=500)

    @route("health_metrics", "/api/health", methods=["GET", "OPTIONS"])
    def get_health_metrics(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_health_metrics()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health: %s", e)
            return self.error_response(e, status=500)

    @route("health_summary", "/api/health/summary", methods=["GET", "OPTIONS"])
    def get_health_summary(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.get_health_summary()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health/summary: %s", e)
            return self.error_response(e, status=500)

    @route("switch_ports", "/api/switch/{dpid}/ports", methods=["GET", "OPTIONS"])
    def get_switch_ports(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.get_switch_ports(dpid)
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/ports: %s", kwargs.get("dpid"), e)
            return self.error_response(e, status=500)

    @route("switch_flows", "/api/switch/{dpid}/flows", methods=["GET", "OPTIONS"])
    def get_switch_flows(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.get_switch_flows(dpid)
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/flows: %s", kwargs.get("dpid"), e)
            return self.error_response(e, status=500)
