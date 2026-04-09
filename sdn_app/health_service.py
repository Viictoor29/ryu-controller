import time


class HealthService:
    def __init__(self, app):
        self.app = app

    def get_port_health(self, dpid, port_no):
        dpid = str(dpid)
        port_no = int(port_no)

        stats = self.app.stats_monitor.port_stats.get(dpid, {}).get(port_no, {})
        speed = self.app.stats_monitor.port_speed.get(dpid, {}).get(port_no, {
            "bps": 0,
            "kbps": 0,
            "mbps": 0
        })

        total_errors = stats.get("rx_errors", 0) + stats.get("tx_errors", 0)
        total_drops = stats.get("rx_dropped", 0) + stats.get("tx_dropped", 0)

        if total_errors > 0:
            status = "degraded"
        elif total_drops > 0:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
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
        self.app.topology_service.sync_links_inventory()

        switches_health = []

        for dpid in sorted(self.app.datapaths.keys()):
            dpid_str = str(dpid)

            ports = []
            dpid_port_stats = self.app.stats_monitor.port_stats.get(dpid_str, {})
            dpid_port_speed = self.app.stats_monitor.port_speed.get(dpid_str, {})
            dpid_flows = self.app.stats_monitor.flow_stats.get(dpid_str, [])

            total_rx_errors = 0
            total_tx_errors = 0
            total_rx_dropped = 0
            total_tx_dropped = 0
            total_bps = 0

            for port_no in sorted(dpid_port_stats.keys()):
                stats = dpid_port_stats.get(port_no, {})
                speed = dpid_port_speed.get(port_no, {
                    "bps": 0,
                    "kbps": 0,
                    "mbps": 0
                })

                total_rx_errors += stats.get("rx_errors", 0)
                total_tx_errors += stats.get("tx_errors", 0)
                total_rx_dropped += stats.get("rx_dropped", 0)
                total_tx_dropped += stats.get("tx_dropped", 0)
                total_bps += speed.get("bps", 0)

                port_status = "healthy"
                if stats.get("rx_errors", 0) + stats.get("tx_errors", 0) > 0:
                    port_status = "degraded"
                elif stats.get("rx_dropped", 0) + stats.get("tx_dropped", 0) > 0:
                    port_status = "warning"

                ports.append({
                    "port_no": port_no,
                    "status": port_status,
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

        for sw in health["switches"]:
            total_flows += sw.get("flow_count", 0)
            total_bps += sw.get("traffic", {}).get("bps", 0)

            if sw["status"] == "healthy":
                healthy_switches += 1
            elif sw["status"] == "warning":
                warning_switches += 1
            elif sw["status"] == "degraded":
                degraded_switches += 1

            for port in sw.get("ports", []):
                if port["status"] == "healthy":
                    healthy_ports += 1
                elif port["status"] == "warning":
                    warning_ports += 1
                elif port["status"] == "degraded":
                    degraded_ports += 1

        links_total = len(self.app.topology_service.links_inventory)
        links_enabled = len([
            l for l in self.app.topology_service.links_inventory.values()
            if l.get("enabled", False)
        ])
        links_discovered = len([
            l for l in self.app.topology_service.links_inventory.values()
            if l.get("discovered", False)
        ])

        return {
            "timestamp": int(time.time()),
            "controller_uptime_seconds": int(time.time() - self.app.start_time),
            "switches": {
                "total": health["switch_count"],
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
                degraded_switches, warning_switches, degraded_ports, warning_ports
            )
        }

    def get_switch_ports(self, dpid):
        dpid = str(dpid)

        if dpid not in self.app.stats_monitor.port_stats:
            return {
                "dpid": dpid,
                "ports": []
            }

        ports = []
        for port_no in sorted(self.app.stats_monitor.port_stats[dpid].keys()):
            ports.append({
                "port_no": port_no,
                "health": self.get_port_health(dpid, port_no)
            })

        return {
            "dpid": dpid,
            "ports": ports
        }

    def get_switch_flows(self, dpid):
        dpid = str(dpid)
        return {
            "dpid": dpid,
            "flow_count": len(self.app.stats_monitor.flow_stats.get(dpid, [])),
            "flows": self.app.stats_monitor.flow_stats.get(dpid, [])
        }