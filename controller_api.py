from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response

from ryu.topology.api import get_switch, get_link, get_host
import json
import time
import traceback


API_INSTANCE_NAME = "sdn_api_app"

class SDNControllerAPI(app_manager.RyuApp):
    _CONTEXTS = {
        "wsgi": WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        super(SDNControllerAPI, self).__init__(*args, **kwargs)

        wsgi = kwargs["wsgi"]
        wsgi.register(SDNRestController, {
            API_INSTANCE_NAME: self
        })

class SDNRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SDNRestController, self).__init__(req, link, data, **config)
        self.sdn_app = data[API_INSTANCE_NAME]

    @route("topology", "/api/topology", methods=["GET"])
    def get_topology(self, req, **kwargs):
        switches = get_switch(self.sdn_app, None)
        links = get_link(self.sdn_app, None)
        hosts = get_host(self.sdn_app, None)

        nodes = []
        edges = []

        # switches → nodos
        for sw in switches:
            nodes.append({
                "id": sw.dp.id,
                "type": "switch"
            })

        # hosts → nodos
        for host in hosts:
            nodes.append({
                "id": host.mac,
                "type": "host",
                "connected_to": host.port.dpid
            })

        # links → aristas
        for link in links:
            edges.append({
                "source": link.src.dpid,
                "target": link.dst.dpid,
                "src_port": link.src.port_no,
                "dst_port": link.dst.port_no
            })

        body = {
            "nodes": nodes,
            "edges": edges
        }

        return Response(
            content_type="application/json",
            charset="utf-8",
            body=json.dumps(body).encode("utf-8")
        )
    
    