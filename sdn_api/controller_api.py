import time
import json
import urllib.request

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
        self.stp_port_state = {}
        self.flow_stats = {}
        self.monitor_interval = 5

        self.mac_to_port = {}
        self.blocked_ports = set()

        # Hosts borrados manualmente.
        # Se ocultan de la topología hasta que vuelvan a generar tráfico.
        self.deleted_host_macs = set()

        self.topology_service = TopologyService(self)
        self.tc_service = TCService(self)
        self.stats_service = StatsService(self)
        self.health_service = HealthService(self)
        self.traffic_service = TrafficService(self)

        self.monitor_thread = hub.spawn(self.stats_service.monitor_loop)

        # STP ready / auto-pingall
        self.stp_last_change = 0
        self.stp_ready = False
        self.stp_ready_since = None
        self.stp_ready_delay = 8
        self.stp_auto_pingall = True
        self.stp_last_pingall = None
        self.stp_last_pingall_result = None
        self.stp_watch_thread = hub.spawn(self.stp_ready_watch_loop)

        self.logger.info("SDNControllerAPI iniciada correctamente con STP")

    def mark_stp_changed(self):
        self.stp_ready = False
        self.stp_ready_since = None
        self.stp_last_change = time.time()

    def get_stp_status(self):
        return {
            "ready": bool(self.stp_ready),
            "ready_since": int(self.stp_ready_since) if self.stp_ready_since else None,
            "last_change": int(self.stp_last_change) if self.stp_last_change else None,
            "ready_delay_seconds": self.stp_ready_delay,
            "auto_pingall": bool(self.stp_auto_pingall),
            "last_pingall": int(self.stp_last_pingall) if self.stp_last_pingall else None,
            "last_pingall_result": self.stp_last_pingall_result,
            "ports": self.stp_port_state,
            "blocked_ports": [
                {"dpid": dpid, "port_no": port_no}
                for dpid, port_no in sorted(self.blocked_ports)
            ],
        }

    def stp_ports_are_final(self):
        for ports in self.stp_port_state.values():
            for state in ports.values():
                if state is None:
                    continue
                if int(state) not in (
                    stplib.PORT_STATE_DISABLE,
                    stplib.PORT_STATE_BLOCK,
                    stplib.PORT_STATE_FORWARD,
                ):
                    return False
        return True

    def stp_ready_watch_loop(self):
        while True:
            hub.sleep(1)

            try:
                if not self.stp_last_change:
                    continue

                quiet_for = time.time() - self.stp_last_change

                if self.stp_ready:
                    continue

                if quiet_for < self.stp_ready_delay:
                    continue

                if not self.stp_ports_are_final():
                    continue

                self.stp_ready = True
                self.stp_ready_since = time.time()

                self.logger.info(
                    "STP convergido tras %.1fs sin cambios",
                    quiet_for,
                )

                if self.stp_auto_pingall:
                    self.logger.info(
                        "Ejecutando pingall automático tras convergencia STP"
                    )

                    hub.sleep(3)
                    result = self.call_mininet_pingall()

                    self.stp_last_pingall = time.time()
                    self.stp_last_pingall_result = result

                    data = result.get("data", result)

                    success = data.get("success")
                    failed = data.get("failed_tests")
                    total = data.get("total_tests")

                    if success is None and "packet_loss_percent" in data:
                        success = float(data.get("packet_loss_percent", 100)) == 0.0

                    self.logger.info(
                        "Pingall STP terminado: success=%s failed=%s total=%s loss=%s",
                        success,
                        failed,
                        total,
                        data.get("packet_loss_percent"),
                    )

            except Exception as e:
                self.stp_last_pingall = time.time()
                self.stp_last_pingall_result = {
                    "success": False,
                    "error": str(e),
                }
                self.logger.exception("Error en watcher STP/pingall: %s", e)

    def topology_get_switches(self):
        return get_switch(self, None)

    def topology_get_links(self):
        return get_link(self, None)

    def topology_get_hosts(self):
        return get_host(self, None)

    def call_mininet_pingall(self):
        payload = json.dumps({"timeout": 30}).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:8081/api/mininet/pingall",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def is_port_blocked(self, dpid, port_no):
        return (int(dpid), int(port_no)) in self.blocked_ports

    def add_flow(
        self,
        datapath,
        priority,
        match,
        actions,
        buffer_id=None,
        idle_timeout=0,
        hard_timeout=0,
    ):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        kwargs = {
            "datapath": datapath,
            "priority": priority,
            "match": match,
            "instructions": inst,
            "idle_timeout": idle_timeout,
            "hard_timeout": hard_timeout,
        }

        if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
            kwargs["buffer_id"] = buffer_id

        datapath.send_msg(parser.OFPFlowMod(**kwargs))

    def delete_flows(self, datapath):
        if datapath is None:
            return

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

        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER,
            )
        ]
        self.add_flow(datapath, 0, match, actions)

    def flush_switch_learning(self, datapath):
        if datapath is None:
            return

        dpid = int(datapath.id)
        self.mac_to_port.pop(dpid, None)
        self.delete_flows(datapath)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER,
            )
        ]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Table-miss instalado en switch %s", datapath.id)

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
            self.port_admin_state.pop(str(dpid), None)
            self.stp_port_state.pop(str(dpid), None)

            self.blocked_ports = {
                item for item in self.blocked_ports
                if item[0] != dpid
            }

            for key in list(self.links_inventory.keys()):
                link = self.links_inventory[key]
                if (
                    str(link.get("source")) == str(dpid)
                    or str(link.get("target")) == str(dpid)
                ):
                    link["enabled"] = False
                    link["discovered"] = True
                    link["state"] = "disabled"
                    link["manual_disabled"] = True
                    link["state"] = "switch_removed"
                    link["last_seen"] = int(time.time())

            for key, host_link in list(self.host_links_inventory.items()):
                if str(host_link.get("switch")) == str(dpid):
                    host_link["enabled"] = False
                    host_link["discovered"] = False
                    self.host_links_inventory.pop(key, None)

            self.mark_stp_changed()

    @set_ev_cls(stplib.EventPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        dpid = datapath.id
        in_port = msg.match["in_port"]

        if self.is_port_blocked(dpid, in_port):
            return

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)
        if not eth:
            return

        eth = eth[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst.lower()
        src = eth.src.lower()

        if src in self.deleted_host_macs:
            self.deleted_host_macs.discard(src)
            self.logger.info("Host reaprendido tras tráfico: %s", src)

        if dst.startswith("33:33:"):
            return

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        if out_port != ofproto.OFPP_FLOOD and self.is_port_blocked(dpid, out_port):
            return

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(
                in_port=in_port,
                eth_src=src,
                eth_dst=dst,
            )

            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(
                    datapath,
                    1,
                    match,
                    actions,
                    buffer_id=msg.buffer_id,
                    idle_timeout=30,
                )
                return

            self.add_flow(datapath, 1, match, actions, idle_timeout=30)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

    @set_ev_cls(stplib.EventTopologyChange, MAIN_DISPATCHER)
    def stp_topology_change_handler(self, ev):
        dp = ev.dp

        self.mark_stp_changed()
        self.flush_switch_learning(dp)

    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def stp_port_state_change_handler(self, ev):
        dpid = ev.dp.id
        port_no = ev.port_no
        state = ev.port_state

        self.stp_port_state.setdefault(str(dpid), {})
        self.stp_port_state[str(dpid)][int(port_no)] = int(state)

        if state == stplib.PORT_STATE_BLOCK:
            self.blocked_ports.add((int(dpid), int(port_no)))
        else:
            self.blocked_ports.discard((int(dpid), int(port_no)))

        self.mark_stp_changed()
        self.flush_switch_learning(ev.dp)

        self.logger.info(
            "STP estado puerto: s%s port=%s state=%s blocked=%s",
            dpid,
            port_no,
            state,
            self.is_port_blocked(dpid, port_no),
        )

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
            dst_dpid, dst_port,
        )

        current = self.links_inventory.setdefault(key, {})
        current.update({
            "source": src_dpid,
            "target": dst_dpid,
            "src_port": src_port,
            "dst_port": dst_port,
            "enabled": True,
            "discovered": True,
            "state": "up",
            "manual_disabled": False,
            "last_seen": int(time.time()),
        })

        self.logger.info(
            "Link añadido: s%s:%s <-> s%s:%s",
            src_dpid, src_port, dst_dpid, dst_port,
        )

        self.mark_stp_changed()

    @set_ev_cls(event.EventLinkDelete)
    def link_delete_handler(self, ev):
        link = ev.link

        src_dpid = str(link.src.dpid)
        dst_dpid = str(link.dst.dpid)
        src_port = int(link.src.port_no)
        dst_port = int(link.dst.port_no)

        key = self.topology_service.make_link_key(
            src_dpid, src_port,
            dst_dpid, dst_port,
        )

        current = self.links_inventory.setdefault(key, {
            "source": src_dpid,
            "target": dst_dpid,
            "src_port": src_port,
            "dst_port": dst_port,
        })

        if current.get("state") == "disabled" or current.get("manual_disabled"):
            current["enabled"] = False
            current["discovered"] = True
            current["state"] = "disabled"
        else:
            current["enabled"] = False
            current["discovered"] = False
            current["state"] = "deleted"

        current["last_seen"] = int(time.time())

        self.mark_stp_changed()

        self.logger.info(
            "Link eliminado: s%s:%s <-> s%s:%s state=%s manual_disabled=%s",
            src_dpid,
            src_port,
            dst_dpid,
            dst_port,
            current.get("state"),
            current.get("manual_disabled"),
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

        is_admin_down = bool(desc.config & dp.ofproto.OFPPC_PORT_DOWN)
        is_link_down = bool(desc.state & dp.ofproto.OFPPS_LINK_DOWN)
        admin_state = "down" if is_admin_down or is_link_down else "up"

        self.port_admin_state.setdefault(dpid, {})
        self.port_admin_state[dpid][port_no] = admin_state

        if admin_state == "down":
            self.blocked_ports.discard((int(dpid), int(port_no)))
            self.stp_port_state.setdefault(dpid, {})
            self.stp_port_state[dpid][port_no] = None

            for link in self.links_inventory.values():
                if (
                    str(link.get("source")) == dpid
                    and int(link.get("src_port")) == port_no
                ) or (
                    str(link.get("target")) == dpid
                    and int(link.get("dst_port")) == port_no
                ):
                    link["enabled"] = False
                    link["discovered"] = False

            for host_link in self.host_links_inventory.values():
                if (
                    str(host_link.get("switch")) == dpid
                    and int(host_link.get("switch_port")) == port_no
                ):
                    host_link["enabled"] = False
                    host_link["discovered"] = False

            self.flush_switch_learning(dp)

        self.mark_stp_changed()

        self.logger.info(
            "Port status: s%s port=%s state=%s reason=%s admin_down=%s link_down=%s",
            dpid, port_no, admin_state, reason, is_admin_down, is_link_down,
        )

    def forget_host_by_mac(self, mac):
        """
        Usado por /api/hosts/forget/{mac}.
        Oculta el host de la visualización.
        Si el host vuelve a generar tráfico, packet_in_handler lo reaprende.
        """
        mac = str(mac).lower()

        self.deleted_host_macs.add(mac)

        self.host_links_inventory = {
            k: v for k, v in self.host_links_inventory.items()
            if str(v.get("host_mac", "")).lower() != mac
        }

        self.logger.info("Host eliminado de la visualización: %s", mac)

        return {
            "mac": mac,
            "state": "deleted_from_visual_topology",
        }