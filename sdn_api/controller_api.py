from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication
from ryu.lib import hub
from ryu.topology.api import get_switch, get_link, get_host

from rest_routes import SDNRestController, API_INSTANCE_NAME
from topology_service import TopologyService
from tc_service import TCService
from stats_service import StatsService
from health_service import HealthService
from traffic_service import TrafficService

import time


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
        self.host_links_inventory = {}

        self.port_stats = {}
        self.port_speed = {}
        self.port_admin_state = {}
        self.flow_stats = {}
        self.monitor_interval = 5

        self.topology_service = TopologyService(self)
        self.tc_service = TCService(self)
        self.stats_service = StatsService(self)
        self.health_service = HealthService(self)
        self.traffic_service = TrafficService(self)

        self.monitor_thread = hub.spawn(self.stats_service.monitor_loop)

        self.logger.info("SDNControllerAPI iniciada correctamente")

    # =========================================================
    # TOPOLOGY API WRAPPERS
    # =========================================================

    def topology_get_switches(self):
        return get_switch(self, None)

    def topology_get_links(self):
        return get_link(self, None)

    def topology_get_hosts(self):
        return get_host(self, None)

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
                self.logger.info("Switch conectado: %s", dpid)
            self.datapaths[dpid] = datapath

        elif ev.state == DEAD_DISPATCHER:
            if dpid in self.datapaths:
                del self.datapaths[dpid]
                self.logger.info("Switch desconectado: %s", dpid)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        try:
            self.stats_service.handle_port_stats_reply(ev)
        except Exception as e:
            self.logger.exception("Error procesando EventOFPPortStatsReply: %s", e)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        try:
            self.stats_service.handle_flow_stats_reply(ev)
        except Exception as e:
            self.logger.exception("Error procesando EventOFPFlowStatsReply: %s", e)
            