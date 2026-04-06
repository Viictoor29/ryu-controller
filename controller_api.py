from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response
from ryu.topology.api import get_switch, get_link, get_host
import json


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

        # Guarda los switches conectados para poder enviar PortMod
        self.datapaths = {}

        # Inventario completo de enlaces switch-switch
        # clave: link_key canónica
        # valor: {
        #   "source": "...",
        #   "target": "...",
        #   "src_port": n,
        #   "dst_port": n,
        #   "enabled": True/False
        # }
        self.links_inventory = {}

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
        Sincroniza el inventario con los enlaces actualmente descubiertos por Ryu.
        Los enlaces que aparezcan en get_link() se marcan como enabled=True.
        Los que no aparezcan NO se borran, para poder seguir mostrándolos si fueron desactivados.
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
            # Si no estaba aún en inventario, lo añadimos
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

        # Buscar el puerto en el switch
        port = datapath.ports.get(port_no)
        if port is None:
            raise ValueError(f"No se encontró el puerto {port_no} en el switch {dpid}")

        # up=True => quitar PORT_DOWN
        # up=False => poner PORT_DOWN
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

    def get_topology_data(self):
        # Primero sincronizamos los enlaces activos descubiertos
        self.sync_links_inventory()

        switches = get_switch(self, None)
        hosts = get_host(self, None)

        nodes = []
        edges = []
        seen_nodes = set()

        # switches
        for sw in switches:
            sw_id = str(sw.dp.id)
            if sw_id not in seen_nodes:
                nodes.append({
                    "id": sw_id,
                    "type": "switch"
                })
                seen_nodes.add(sw_id)

        # hosts + enlace host-switch
        for host in hosts:
            host_id = str(host.mac)
            switch_id = str(host.port.dpid)

            if host_id not in seen_nodes:
                nodes.append({
                    "id": host_id,
                    "type": "host"
                })
                seen_nodes.add(host_id)

            edges.append({
                "source": host_id,
                "target": switch_id,
                "type": "host-link",
                "port": int(host.port.port_no),
                "enabled": True
            })

        # enlaces switch-switch desde inventario completo
        for link in self.links_inventory.values():
            edges.append({
                "source": link["source"],
                "target": link["target"],
                "type": "switch-link",
                "src_port": int(link["src_port"]),
                "dst_port": int(link["dst_port"]),
                "enabled": bool(link["enabled"])
            })

        return {
            "nodes": nodes,
            "edges": edges
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
            body=json.dumps(data).encode("utf-8")
        )

    def read_json_body(self, req):
        if not req.body:
            return {}
        return json.loads(req.body.decode("utf-8"))

    @route("topology", "/api/topology", methods=["GET"])
    def get_topology(self, req, **kwargs):
        try:
            body = self.sdn_app.get_topology_data()
            return self.json_response(body)
        except Exception as e:
            return self.json_response({
                "ok": False,
                "error": str(e)
            }, status=500)

    @route("disable_link", "/api/links/disable", methods=["POST"])
    def disable_link(self, req, **kwargs):
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

    @route("enable_link", "/api/links/enable", methods=["POST"])
    def enable_link(self, req, **kwargs):
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