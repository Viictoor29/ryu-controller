import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    DEAD_DISPATCHER,
    set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication
from ryu.lib import hub
from ryu.lib import stplib
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.topology.api import get_switch, get_link, get_host
from ryu.topology import event

from rest_routes import SDNRestController, API_INSTANCE_NAME
from topology_service import TopologyService
from tc_service import TCService
from stats_service import StatsService
from health_service import HealthService
from traffic_service import TrafficService


class SDNControllerAPI(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "wsgi": WSGIApplication,
        "stplib": stplib.Stp,
    }

    def __init__(self, *args, **kwargs):
        super(SDNControllerAPI, self).__init__(*args, **kwargs)

        wsgi = kwargs["wsgi"]
        wsgi.register(SDNRestController, {API_INSTANCE_NAME: self})

        self.stp = kwargs["stplib"]

        self.start_time = time.time()
        self.datapaths = {}

        self.links_inventory = {}
        self.host_links_inventory = {}

        self.port_stats = {}
        self.port_speed = {}
        self.port_admin_state = {}
        self.flow_stats = {}
        self.monitor_interval = 5

        self.mac_to_port = {}
        self.blocked_ports = set()

        self.topology_service = TopologyService(self)
        self.tc_service = TCService(self)
        self.stats_service = StatsService(self)
        self.health_service = HealthService(self)
        self.traffic_service = TrafficService(self)

        self.monitor_thread = hub.spawn(self.stats_service.monitor_loop)

        self.logger.info("SDNControllerAPI iniciada correctamente con STP")

    # =========================================================
    # TOPOLOGY
    # =========================================================

    def topology_get_switches(self):
        return get_switch(self, None)

    def topology_get_links(self):
        return get_link(self, None)

    def topology_get_hosts(self):
        return get_host(self, None)

    # =========================================================
    # FLOW HELPERS
    # =========================================================

    def is_port_blocked(self, dpid, port_no):
        return (int(dpid), int(port_no)) in self.blocked_ports

    def add_flow(self, datapath, priority, match, actions,
                 buffer_id=None, idle_timeout=0, hard_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
            mod = parser.OFPFlowMod(
                datapath=datapath,
                buffer_id=buffer_id,
                priority=priority,
                match=match,
                instructions=inst,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=priority,
                match=match,
                instructions=inst,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
            )

        datapath.send_msg(mod)

    def delete_flows(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            priority=1,
            match=parser.OFPMatch(),
        )
        datapath.send_msg(mod)

        # reinstalar table-miss
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER
            )
        ]
        self.add_flow(datapath, 0, match, actions)

    # =========================================================
    # SWITCH FEATURES
    # =========================================================

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER
            )
        ]

        self.add_flow(datapath, 0, match, actions)

        self.logger.info("Table-miss instalado en switch %s", datapath.id)

    # =========================================================
    # DATAPATH STATE
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

            self.mac_to_port.pop(dpid, None)

    # =========================================================
    # LEARNING SWITCH + STP
    # =========================================================

    @set_ev_cls(stplib.EventPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        dpid = datapath.id
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)

        if not eth:
            return

        eth = eth[0]

        # Ignorar LLDP
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        # Ignorar IPv6 multicast spam
        if dst.startswith("33:33:"):
            return

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        self.logger.info(
            "PACKET_IN s%s in_port=%s src=%s dst=%s out=%s",
            dpid, in_port, src, dst, out_port
        )

        if out_port != ofproto.OFPP_FLOOD and self.is_port_blocked(dpid, out_port):
            return

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(
                in_port=in_port,
                eth_src=src,
                eth_dst=dst
            )

            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(
                    datapath,
                    1,
                    match,
                    actions,
                    buffer_id=msg.buffer_id,
                    idle_timeout=30
                )
                return
            else:
                self.add_flow(
                    datapath,
                    1,
                    match,
                    actions,
                    idle_timeout=30
                )

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )

        datapath.send_msg(out)

    # =========================================================
    # STP EVENTS
    # =========================================================

    @set_ev_cls(stplib.EventTopologyChange, MAIN_DISPATCHER)
    def stp_topology_change_handler(self, ev):
        dp = ev.dp
        dpid = dp.id

        self.logger.info("STP cambio de topología en switch %s", dpid)

        self.mac_to_port.pop(dpid, None)

    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def stp_port_state_change_handler(self, ev):
        dpid = ev.dp.id
        port_no = ev.port_no
        state = ev.port_state

        if state == stplib.PORT_STATE_BLOCK:
            self.blocked_ports.add((int(dpid), int(port_no)))
        else:
            self.blocked_ports.discard((int(dpid), int(port_no)))

        self.logger.info("STP estado puerto: s%s port=%s state=%s",
                         dpid, port_no, state)

    # =========================================================
    # STATS
    # =========================================================

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

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        link = ev.link

        src_dpid = str(link.src.dpid)
        dst_dpid = str(link.dst.dpid)
        src_port = int(link.src.port_no)
        dst_port = int(link.dst.port_no)

        key = self.topology_service.make_link_key(
            src_dpid, src_port,
            dst_dpid, dst_port
        )

        self.links_inventory[key] = {
            "source": src_dpid,
            "target": dst_dpid,
            "src_port": src_port,
            "dst_port": dst_port,
            "enabled": True,
            "discovered": True,
        }

        self.logger.info(
            "Link añadido: s%s:%s <-> s%s:%s",
            src_dpid, src_port, dst_dpid, dst_port
        )


    @set_ev_cls(event.EventLinkDelete)
    def link_delete_handler(self, ev):
        link = ev.link

        src_dpid = str(link.src.dpid)
        dst_dpid = str(link.dst.dpid)
        src_port = int(link.src.port_no)
        dst_port = int(link.dst.port_no)

        key = self.topology_service.make_link_key(
            src_dpid, src_port,
            dst_dpid, dst_port
        )

        if key in self.links_inventory:
            self.links_inventory[key]["enabled"] = False
            self.links_inventory[key]["discovered"] = False
        else:
            self.links_inventory[key] = {
                "source": src_dpid,
                "target": dst_dpid,
                "src_port": src_port,
                "dst_port": dst_port,
                "enabled": False,
                "discovered": False,
            }

        self.logger.info(
            "Link eliminado: s%s:%s <-> s%s:%s",
            src_dpid, src_port, dst_dpid, dst_port
        )

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        dpid = str(dp.id)
        port_no = int(msg.desc.port_no)

        if port_no > dp.ofproto.OFPP_MAX:
            return

        reason = msg.reason
        desc = msg.desc

        is_down = bool(desc.config & dp.ofproto.OFPPC_PORT_DOWN)
        is_link_down = bool(desc.state & dp.ofproto.OFPPS_LINK_DOWN)

        admin_state = "down" if is_down or is_link_down else "up"

        self.port_admin_state.setdefault(dpid, {})
        self.port_admin_state[dpid][port_no] = admin_state

        self.logger.info(
            "Port status: s%s port=%s state=%s reason=%s",
            dpid, port_no, admin_state, reason
        )

        if admin_state == "down":
            for key, link in self.links_inventory.items():
                if (
                    str(link.get("source")) == dpid
                    and int(link.get("src_port")) == port_no
                ) or (
                    str(link.get("target")) == dpid
                    and int(link.get("dst_port")) == port_no
                ):
                    link["enabled"] = False
                    link["discovered"] = False