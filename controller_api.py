from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response
from ryu.topology.api import get_switch, get_link, get_host
import json
import subprocess
import re
import time
import platform


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

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if datapath is None:
            return

        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.datapaths[datapath.id] = datapath
                self.logger.info("Switch conectado: %s", datapath.id)

        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]
                self.logger.info("Switch desconectado: %s", datapath.id)

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return tuple(sorted([a, b]))

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.
        Los enlaces detectados se marcan como enabled=True.
        Los que desaparecen no se borran para poder seguir mostrándolos
        si han sido deshabilitados.
        """
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
                    "enabled": True
                }
            else:
                self.links_inventory[key]["enabled"] = True

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
                "enabled": enabled
            }

    def set_port_state(self, dpid, port_no, up=True):
        dpid = int(dpid)
        port_no = int(port_no)

        datapath = self.datapaths.get(dpid)
        if datapath is None:
            raise ValueError(f"No se encontró el switch {dpid}")

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        port = datapath.ports.get(port_no)
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
        """
        Convierte dpid+puerto en nombre de interfaz Mininet.
        Ejemplo: dpid=1, port=2 -> s1-eth2
        """
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
        self.logger.info("tc qdisc show dev %s -> rc=%s out=%s err=%s", iface, rc, qdisc_out, qdisc_err)

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
        self.logger.info("tc class show dev %s -> rc=%s out=%s err=%s", iface, rc, class_out, class_err)

        if rc == 0 and class_out:
            bw_match_class = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", class_out)
            if bw_match_class:
                result["bandwidth"] = bw_match_class.group(1)

        return result

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

            # Se devuelve el estado observado en ambos extremos.
            # También se deja un resumen principal tomando el extremo src.
            edges.append({
                "source": link["source"],
                "target": link["target"],
                "type": "switch-link",
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": bool(link["enabled"]),
                "delay": src_tc["delay"],
                "loss": src_tc["loss"],
                "bandwidth": src_tc["bandwidth"],
            })

        return {
            "nodes": nodes,
            "edges": edges
        }

    def normalize_bandwidth(self, value):
        """
        Acepta valores como:
        - "10mbit"
        - "100kbit"
        - "1gbit"
        - 10   -> "10mbit" (por defecto)
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}mbit"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(kbit|mbit|gbit)$", value):
            return value

        raise ValueError("Formato de bandwidth inválido. Usa por ejemplo: 10mbit, 100kbit, 1gbit")

    def normalize_delay(self, value):
        """
        Acepta valores como:
        - "100ms"
        - "1s"
        - 50 -> "50ms" (por defecto)
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}ms"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(ms|s|us)$", value):
            return value

        raise ValueError("Formato de delay inválido. Usa por ejemplo: 100ms, 1s, 500us")

    def normalize_loss(self, value):
        """
        Acepta valores como:
        - 5
        - 0.5
        - "10"
        Devuelve float.
        """
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
        """
        Elimina configuración tc previa de una interfaz.
        """
        self.run_command(["sudo", "tc", "qdisc", "del", "dev", iface, "root"])
        # no importa si falla porque no existía

    def set_interface_tc(self, iface, delay=None, loss=None, bandwidth=None):
        """
        Aplica tc sobre una interfaz usando netem.
        Usa:
          tc qdisc replace dev IFACE root netem delay X loss Y% rate Z

        Nota:
        - netem soporta delay/loss.
        - rate puede funcionar para limitar ancho de banda de forma simple.
        - si no se recibe ningún parámetro, elimina tc.
        """
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
        """
        Aplica tc en ambos extremos del enlace.
        """
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

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.OFP_VERSIONS,
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