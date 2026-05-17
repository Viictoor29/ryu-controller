import time


class StateServiceMixin:
    """Estado, exportación de topología y diagnóstico."""

    def status(self):
        with self.lock:
            return {
                "hosts": [host.name for host in sorted(self.net.hosts, key=lambda h: h.name)],
                "switches": [sw.name for sw in sorted(self.net.switches, key=lambda s: s.name)],
                "links": [str(link) for link in self.net.links],
                "topology": self.export_topology_locked(),
            }

    def export_topology(self):
        with self.lock:
            return self.export_topology_locked()

    def export_topology_locked(self):
        switches = []
        hosts = []
        links = []

        switch_by_name = {sw.name: sw for sw in self.net.switches}
        host_by_name = {host.name: host for host in self.net.hosts}

        for sw in sorted(self.net.switches, key=lambda s: s.name):
            switches.append({
                "name": sw.name,
                "dpid": self.dpid_from_switch(sw),
            })

        hosts_by_name = {}
        for host in sorted(self.net.hosts, key=lambda h: h.name):
            host_data = {
                "name": host.name,
                "ip": self.safe_host_ip(host),
                "mac": self.safe_host_mac(host),
            }
            hosts_by_name[host.name] = host_data
            hosts.append(host_data)

        for link in list(self.net.links):
            n1 = link.intf1.node
            n2 = link.intf2.node
            n1_name = n1.name
            n2_name = n2.name
            p1 = self.port_from_intf(link.intf1)
            p2 = self.port_from_intf(link.intf2)

            n1_is_sw = n1_name in switch_by_name
            n2_is_sw = n2_name in switch_by_name
            n1_is_host = n1_name in host_by_name
            n2_is_host = n2_name in host_by_name

            if n1_is_sw and n2_is_sw:
                links.append({
                    "type": "switch-link",
                    "src": {"node": n1_name, "dpid": self.dpid_from_switch(n1), "port_no": p1},
                    "dst": {"node": n2_name, "dpid": self.dpid_from_switch(n2), "port_no": p2},
                })
                continue

            if n1_is_host and n2_is_sw:
                hosts_by_name[n1_name]["switch"] = n2_name
                hosts_by_name[n1_name]["switch_dpid"] = self.dpid_from_switch(n2)
                hosts_by_name[n1_name]["switch_port"] = p2
                continue

            if n2_is_host and n1_is_sw:
                hosts_by_name[n2_name]["switch"] = n1_name
                hosts_by_name[n2_name]["switch_dpid"] = self.dpid_from_switch(n1)
                hosts_by_name[n2_name]["switch_port"] = p1
                continue

        return {
            "kind": "mininet_live_topology",
            "exported_at": int(time.time()),
            "mininet": {
                "switches": switches,
                "hosts": hosts,
                "links": links,
            },
            "last_applied_scenario": self.last_applied_scenario,
        }

    def ping_all(self):
        with self.lock:
            loss = self.net.pingAll()
            return {"packet_loss_percent": loss}
