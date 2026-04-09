from ryu.lib import hub
import time


class StatsMonitor:
    def __init__(self, app):
        self.app = app
        self.port_stats = {}
        self.port_speed = {}
        self.flow_stats = {}

        self.monitor_interval = 5
        self.monitor_thread = hub.spawn(self._monitor)

    def _monitor(self):
        while True:
            for datapath in list(self.app.datapaths.values()):
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
            self.app.logger.error(
                "Error solicitando stats al switch %s: %s",
                datapath.id, e
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
                prev_total_bytes = prev["rx_bytes"] + prev["tx_bytes"]
                current_total_bytes = current["rx_bytes"] + current["tx_bytes"]
                delta_bytes = current_total_bytes - prev_total_bytes
                delta_time = now - prev["timestamp"]

                bps = (delta_bytes * 8 / delta_time) if delta_time > 0 else 0
                self.port_speed[dpid][port_no] = {
                    "bps": round(bps, 2),
                    "kbps": round(bps / 1000, 3),
                    "mbps": round(bps / 1000000, 6)
                }
            else:
                self.port_speed[dpid][port_no] = {
                    "bps": 0,
                    "kbps": 0,
                    "mbps": 0
                }

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

    def get_port_stats(self, dpid):
        return self.port_stats.get(str(dpid), {})

    def get_port_speed(self, dpid):
        return self.port_speed.get(str(dpid), {})

    def get_flow_stats(self, dpid):
        return self.flow_stats.get(str(dpid), [])