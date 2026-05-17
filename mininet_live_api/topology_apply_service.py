class TopologyApplyServiceMixin:
    """Aplicación y limpieza de topologías completas."""

    def apply_topology(self, body):
        scenario = self.normalize_scenario_body(body)
        mininet_spec = scenario["mininet"]

        with self.lock:
            clear_result = self.clear_topology_locked(notify_ryu=False)

            created_switches = []
            created_hosts = []
            created_links = []
            skipped_links = []
            seen_link_keys = set()

            for switch in mininet_spec.get("switches", []) or []:
                created_switches.append(self._create_switch(switch).name)

            for host in mininet_spec.get("hosts", []) or []:
                created_hosts.append(self._create_host(host).name)

            # Primero enlaces explícitos. Pueden ser switch-switch o host-switch.
            for link in mininet_spec.get("links", []) or []:
                try:
                    normalized = self.normalize_link_body(link)
                    key = self.normalized_link_key(normalized)
                    if key in seen_link_keys:
                        skipped_links.append({"link": link, "reason": "duplicated"})
                        continue
                    seen_link_keys.add(key)
                    created_links.append(self._add_link_locked(normalized))
                except Exception as e:
                    raise RuntimeError(f"Error creando link {link}: {e}")

            # Después host.switch para mantener compatibilidad con el export/import.
            for host in mininet_spec.get("hosts", []) or []:
                host_name = str(host.get("name", "")).lower()
                switch_name = host.get("switch") or host.get("switch_name")
                switch_dpid = host.get("switch_dpid")
                if not switch_name and switch_dpid is not None:
                    switch_name = self.switch_name_from_dpid(switch_dpid)
                if not host_name or not switch_name:
                    continue

                link_body = {
                    "node1": host_name,
                    "node2": str(switch_name).lower(),
                }
                if host.get("switch_port") is not None:
                    link_body["port2"] = int(host["switch_port"])

                normalized = self.normalize_link_body(link_body)
                key = self.normalized_link_key(normalized)
                if key in seen_link_keys or self.links_between_nodes_exist(normalized["node1"], normalized["node2"]):
                    skipped_links.append({"link": link_body, "reason": "already_exists"})
                    continue

                seen_link_keys.add(key)
                created_links.append(self._add_link_locked(normalized))

            self.last_applied_scenario = scenario

            return {
                "state": "topology_applied",
                "clear": clear_result,
                "created": {
                    "switches": created_switches,
                    "hosts": created_hosts,
                    "links": created_links,
                    "skipped_links": skipped_links,
                },
                "status": self.status(),
            }

    def clear_topology(self, notify_ryu=False):
        with self.lock:
            return self.clear_topology_locked(notify_ryu=notify_ryu)

    def clear_topology_locked(self, notify_ryu=False):
        removed_links = []
        removed_hosts = []
        removed_switches = []

        for link in list(self.net.links):
            if notify_ryu:
                self.notify_ryu_before_link_delete(link)
            removed_links.append(str(link))
            try:
                self.net.delLink(link)
            except Exception as e:
                removed_links.append({"link": str(link), "error": str(e)})

        for host in list(self.net.hosts):
            if notify_ryu:
                try:
                    mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)
                    if mac:
                        self.notify_ryu_forget_host(mac)
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu para olvidar host: {e}")
            removed_hosts.append(host.name)
            try:
                self.net.delHost(host)
            except Exception as e:
                removed_hosts.append({"host": host.name, "error": str(e)})

        for sw in list(self.net.switches):
            removed_switches.append(sw.name)
            try:
                sw.stop()
            except Exception:
                pass
            try:
                self.net.delSwitch(sw)
            except Exception as e:
                removed_switches.append({"switch": sw.name, "error": str(e)})

        self.last_applied_scenario = None

        return {
            "removed_links": removed_links,
            "removed_hosts": removed_hosts,
            "removed_switches": removed_switches,
            "state": "cleared",
        }
