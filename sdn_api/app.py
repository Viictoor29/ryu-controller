import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication

from constants import API_INSTANCE_NAME
from controllers.rest_controller import SDNRestController
from services.tc_service import TcService
from services.topology_service import TopologyService
from services.link_service import LinkService
from services.stats_service import StatsService
from services.health_service import HealthService


class SDNControllerAPI(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "wsgi": WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        wsgi = kwargs["wsgi"]
        wsgi.register(SDNRestController, {API_INSTANCE_NAME: self})

        self.start_time = time.time()
        self.datapaths = {}
        self.links_inventory = {}

        self.port_stats = {}
        self.port_speed = {}
        self.flow_stats = {}
        self.monitor_interval = 5

        self.tc_service = TcService(self)
        self.topology_service = TopologyService(self, self.tc_service)
        self.link_service = LinkService(self, self.topology_service, self.tc_service)
        self.stats_service = StatsService(self)
        self.health_service = HealthService(self, self.topology_service)

        self.stats_service.start_monitor()

        self.logger.info("SDNControllerAPI iniciada correctamente")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, "dead"])
    def state_change_handler(self, ev):
        try:
            self.stats_service.handle_state_change(ev)
        except Exception as e:
            self.logger.exception("Error procesando EventOFPStateChange: %s", e)

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