import time

from rest_helpers import (
    empty_speed,
    compute_port_status,
    compute_overall_status,
)


class HealthService:
    def __init__(self, app):
        self.app = app

    def _empty_speed(self):
        return empty_speed()

    def _compute_port_status(self, stats):
        return compute_port_status(stats)

    def compute_overall_status(self, degraded_switches, warning_switches, degraded_ports, warning_ports):
        return compute_overall_status(
            degraded_switches,
            warning_switches,
            degraded_ports,
            warning_ports
        )

    def get_port_health(self, dpid, port_no):
        dpid = str(dpid)
        port_no = int(port_no)

        stats = self.app.port_stats.get(dpid, {}).get(port_no, {})
        speed = self.app.port_speed.get(dpid, {}).get(port_no, self._empty_speed())

        return {
            "status": self._compute_port_status(stats),
            "stats": stats,
            "speed": speed
        }

    def get_health_metrics(self):
        try:
            self.app.topology_service.sync_links_inventory()
        except Exception as e:
            self.app.logger.exception("Error sincronizando inventario de enlaces: %s", e)

        switches_health = []

        for dpid in sorted(self.app.datapaths.keys()):
            dpid_str = str(dpid)

            ports = []
            dpid_port_stats = self.app.port_stats.get(dpid_str, {})
            dpid_port_speed = self.app.port_speed.get(dpid_str, {})
            dpid_flows = self.app.flow_stats.get(dpid_str, [])

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
            "controller_uptime_seconds": int(time.time() - self.app.start_time),
            "switch_count": len(self.app.datapaths),
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

        links_inventory = self.app.links_inventory
        links_total = len(links_inventory)
        links_enabled = len([link for link in links_inventory.values() if link.get("enabled", False)])
        links_discovered = len([link for link in links_inventory.values() if link.get("discovered", False)])

        return {
            "timestamp": int(time.time()),
            "controller_uptime_seconds": int(time.time() - self.app.start_time),
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

        if dpid not in self.app.port_stats:
            return {
                "dpid": dpid,
                "ports": []
            }

        ports = []
        for port_no in sorted(self.app.port_stats[dpid].keys()):
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
        flows = self.app.flow_stats.get(dpid, [])

        return {
            "dpid": dpid,
            "flow_count": len(flows),
            "flows": flows
        }

    def get_controller_status(self):
        uptime_seconds = int(time.time() - self.app.start_time)

        return {
            "controller": {
                "name": "Ryu SDN Controller",
                "status": "running",
                "uptime_seconds": uptime_seconds,
                "ofp_versions": self.app.OFP_VERSIONS,
                "monitor_interval_seconds": self.app.monitor_interval
            },
            "summary": {
                "switches_connected": len(self.app.datapaths),
                "port_stats_switches": len(self.app.port_stats),
                "flow_stats_switches": len(self.app.flow_stats),
                "links_inventory": len(self.app.links_inventory)
            }
        }