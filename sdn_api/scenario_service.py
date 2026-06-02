import ipaddress
import json
import time
import urllib.error
import urllib.request

from ryu.lib import hub


class ScenarioService:
    """
    Importa/exporta escenarios de topología.

    Responsabilidad:
    - Exportar la topología actual usando get_topology_data().
    - Normalizar topologías que vienen desde la web.
    - Enviar la topología normalizada a la API de Mininet.
    - Limpiar estado runtime del controller y aplicar políticas persistidas.

    Nota importante: este servicio NO crea switches dentro de Ryu. La creación real
    debe hacerla Mininet. Ryu después descubre switches/links/hosts normalmente.
    """

    DEFAULT_MININET_APPLY_URL = "http://127.0.0.1:8081/api/mininet/topology/apply"

    def __init__(self, app):
        self.app = app

    # ---------------------------------------------------------------------
    # Export
    # ---------------------------------------------------------------------
    def export_current_topology(self, name=None, include_runtime=False, include_controller=False):
        topology = self.app.topology_service.get_topology_data()
        mininet = self._build_mininet_from_topology(topology)
        policies = self._build_policies_from_topology(topology)

        scenario = {
            "kind": "sdn_topology_scenario",
            "version": 1,
            "name": name or "exported-topology",
            "exported_at": int(time.time()),
            "mininet": mininet,
            "policies": policies,
        }

        # Foto visual/runtime de Ryu. No hace falta para reimportar.
        if include_runtime:
            scenario["topology"] = topology

        # Estado interno del controlador. Útil para debug, no para escenario normal.
        if include_controller:
            scenario["controller"] = {
                "blocked_ips": sorted(getattr(self.app, "blocked_ips", set())),
                "deleted_host_macs": sorted(getattr(self.app, "deleted_host_macs", set())),
                "detached_host_macs": sorted(getattr(self.app, "detached_host_macs", set())),
            }

        return scenario

    def _build_mininet_from_topology(self, topology):
        nodes = topology.get("nodes", []) or []
        edges = topology.get("edges", []) or []

        switches = []
        hosts_by_id = {}
        links = []

        for node in nodes:
            node_type = node.get("type")
            node_id = str(node.get("id", ""))

            if node_type == "switch" or node_id.upper().startswith("S"):
                dpid = self._dpid_from_switch_id(node_id)
                switches.append({
                    "name": self._switch_name_from_dpid(dpid),
                    "dpid": dpid,
                })
                continue

            if node_type == "host" or node_id.upper().startswith("H"):
                host_name = self._host_name_from_node(node)
                ipv4 = list(node.get("ipv4", []) or [])
                host = {
                    "name": host_name,
                    "mac": node.get("mac"),
                    "ip": ipv4[0] if ipv4 else node.get("ip"),
                    "ipv4": ipv4,
                    "ipv6": list(node.get("ipv6", []) or []),
                }
                hosts_by_id[node_id] = host

        for edge in edges:
            edge_type = edge.get("type")

            if edge_type == "switch-link":
                src_dpid = self._dpid_from_switch_id(edge.get("source"))
                dst_dpid = self._dpid_from_switch_id(edge.get("target"))
                links.append({
                    "type": "switch-link",
                    "src": {
                        "node": self._switch_name_from_dpid(src_dpid),
                        "dpid": src_dpid,
                        "port_no": int(edge.get("src_port")),
                    },
                    "dst": {
                        "node": self._switch_name_from_dpid(dst_dpid),
                        "dpid": dst_dpid,
                        "port_no": int(edge.get("dst_port")),
                    },
                })
                continue

            if edge_type == "host-link":
                host_id = str(edge.get("source-h"))
                switch_dpid = self._dpid_from_switch_id(edge.get("target-s"))
                host = hosts_by_id.get(host_id)
                if host is not None:
                    host["switch"] = self._switch_name_from_dpid(switch_dpid)
                    host["switch_dpid"] = switch_dpid
                    host["switch_port"] = int(edge.get("s-port"))

        return {
            "switches": sorted(switches, key=lambda item: int(item.get("dpid", 0))),
            "hosts": sorted(hosts_by_id.values(), key=lambda item: self._natural_name_key(item.get("name"))),
            "links": links,
        }

    def _build_policies_from_topology(self, topology):
        blocked_ips = set(getattr(self.app, "blocked_ips", set()))
        blocked_ips.update(self._extract_blocked_ips_from_topology(topology))

        policies = {
            "disabled_links": [],
            "disabled_ports": [],
            "tc": [],
            "blocked_ips": self._normalize_blocked_ips(blocked_ips),
        }

        for edge in topology.get("edges", []) or []:
            if edge.get("type") == "switch-link":
                src = {
                    "dpid": self._dpid_from_switch_id(edge.get("source")),
                    "port_no": int(edge.get("src_port")),
                }
                dst = {
                    "dpid": self._dpid_from_switch_id(edge.get("target")),
                    "port_no": int(edge.get("dst_port")),
                }

                if edge.get("manual_disabled") or edge.get("inventory_state") == "disabled":
                    policies["disabled_links"].append({
                        "src": src,
                        "dst": dst,
                        "state": edge.get("state"),
                    })

                policies["tc"].extend(self._tc_rules_for_switch_link(edge, src, dst))

            elif edge.get("type") == "host-link":
                dpid = self._dpid_from_switch_id(edge.get("target-s"))
                port_no = edge.get("s-port")

                if port_no is not None and (
                    edge.get("admin_state") == "down"
                    or edge.get("enabled") is False
                    or edge.get("state") == "down"
                ):
                    policies["disabled_ports"].append({
                        "port": {
                            "dpid": str(dpid),
                            "port_no": int(port_no),
                        },
                        "host": edge.get("source-h"),
                        "state": edge.get("state", "down"),
                    })

                tc = edge.get("tc_sw_port") or {}
                if self._has_tc(tc) and port_no is not None:
                    policies["tc"].append({
                        "type": "port",
                        "port": {"dpid": dpid, "port_no": int(port_no)},
                        **self._compact_tc(tc),
                    })

        return policies

    def _tc_rules_for_switch_link(self, edge, src, dst):
        src_tc = edge.get("src_tc") or {}
        dst_tc = edge.get("dst_tc") or {}
        rules = []

        if not self._has_tc(src_tc) and not self._has_tc(dst_tc):
            return rules

        if self._compact_tc(src_tc) == self._compact_tc(dst_tc):
            rules.append({
                "type": "link",
                "src": src,
                "dst": dst,
                **self._compact_tc(src_tc),
            })
            return rules

        if self._has_tc(src_tc):
            rules.append({
                "type": "port",
                "port": src,
                **self._compact_tc(src_tc),
            })

        if self._has_tc(dst_tc):
            rules.append({
                "type": "port",
                "port": dst,
                **self._compact_tc(dst_tc),
            })

        return rules

    def _has_tc(self, tc):
        return bool(tc and any(tc.get(key) is not None for key in ("delay", "loss", "bandwidth")))

    def _compact_tc(self, tc):
        result = {}
        for key in ("delay", "loss", "bandwidth"):
            value = (tc or {}).get(key)
            if value is not None:
                result[key] = value
        return result

    # ---------------------------------------------------------------------
    # Import / apply
    # ---------------------------------------------------------------------
    def validate_import_payload(self, payload):
        scenario = self.normalize_import_payload(payload)
        errors = self._validate_scenario(scenario)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "scenario": scenario,
        }

    def import_topology_from_web(self, payload):
        options = payload.get("options", {}) if isinstance(payload, dict) else {}
        scenario = self.normalize_import_payload(payload)
        errors = self._validate_scenario(scenario)
        if errors:
            raise ValueError("Topología inválida: " + "; ".join(errors))

        apply_to_mininet = bool(options.get("apply_to_mininet", True))
        reset_controller = bool(options.get("reset_controller", True))
        preserve_blocked_ips = bool(options.get("preserve_blocked_ips", False))
        wait = bool(options.get("wait", True))
        wait_hosts = bool(options.get("wait_hosts", False))
        apply_policies = bool(options.get("apply_policies", True))
        pingall = bool(options.get("pingall", False))
        timeout = float(options.get("timeout", 40))
        mininet_url = options.get("mininet_url") or options.get("mininet_endpoint") or self.DEFAULT_MININET_APPLY_URL

        result = {
            "scenario": scenario,
            "mininet": None,
            "controller_reset": None,
            "host_restore": None,
            "host_cleanup": None,
            "wait": None,
            "policies": None,
            "pingall": None,
        }

        if apply_to_mininet:
            result["mininet"] = self._post_json(mininet_url, scenario, timeout=timeout)
        else:
            result["mininet"] = {
                "skipped": True,
                "reason": "options.apply_to_mininet=false",
            }

        if reset_controller:
            result["controller_reset"] = self.app.reset_runtime_state(
                preserve_blocked_ips=preserve_blocked_ips,
                flush_flows=True,
            )

        result["host_restore"] = self.restore_hosts_from_scenario(scenario)

        expected_host_macs = {
            str(host.get("mac")).strip().lower()
            for host in scenario.get("mininet", {}).get("hosts", [])
            if host.get("mac")
        }

        result["host_cleanup"] = self.app.mark_deleted_hosts_not_in_expected(
            expected_host_macs
        )

        if wait:
            result["wait"] = self.wait_until_topology_ready(
                scenario,
                timeout=timeout,
                wait_hosts=wait_hosts,
            )

        if apply_policies:
            result["policies"] = self.apply_scenario_policies(scenario.get("policies", {}))

        if pingall:
            result["pingall"] = self.app.call_mininet_pingall()

        response_mode = str(options.get("response", "summary")).lower()
        if response_mode in ("full", "verbose", "debug"):
            return result

        return self.compact_import_result(result)
    
    def compact_import_result(self, result):
        scenario = result.get("scenario", {}) or {}
        mininet = scenario.get("mininet", {}) or {}

        mininet_result = result.get("mininet") or {}
        mininet_body = mininet_result.get("body", {}) if isinstance(mininet_result, dict) else {}
        mininet_data = mininet_body.get("data", {}) if isinstance(mininet_body, dict) else {}

        created = mininet_data.get("created", {}) or {}
        clear = mininet_data.get("clear", {}) or {}

        host_restore = result.get("host_restore") or {}
        host_cleanup = result.get("host_cleanup") or {}
        wait = result.get("wait") or {}
        policies = result.get("policies") or {}

        return {
            "state": "imported",
            "name": scenario.get("name"),
            "counts": {
                "switches": len(mininet.get("switches", []) or []),
                "hosts": len(mininet.get("hosts", []) or []),
                "switch_links": len(mininet.get("links", []) or []),

                "created_switches": len(created.get("switches", []) or []),
                "created_hosts": len(created.get("hosts", []) or []),
                "created_links": len(created.get("links", []) or []),

                "removed_links": len(clear.get("removed_links", []) or []),
                "removed_hosts": len(clear.get("removed_hosts", []) or []),
                "removed_switches": len(clear.get("removed_switches", []) or []),
            },
            "hosts": [
                {
                    "name": host.get("name"),
                    "mac": host.get("mac"),
                    "ipv4": host.get("ipv4", []),
                    "connected": host.get("connected"),
                    "state": host.get("state"),
                }
                for host in host_restore.get("restored", []) or []
            ],
            "detached_host_macs": host_restore.get("detached_host_macs", []),
            "stale_macs_hidden": host_cleanup.get("stale_macs_hidden", []),
            "deleted_host_macs": host_cleanup.get("deleted_host_macs", []),
            "ready": wait.get("ready"),
            "wait": {
                "switches_ready": wait.get("switches_ready"),
                "links_ready": wait.get("links_ready"),
                "hosts_ready": wait.get("hosts_ready"),
                "expected_host_count": wait.get("expected_host_count"),
                "active_host_count": wait.get("active_host_count"),
                "timeout": wait.get("timeout"),
            },
            "policies": {
                "disabled_links": len(policies.get("disabled_links", []) or []),
                "disabled_ports": len(policies.get("disabled_ports", []) or []),
                "tc": len(policies.get("tc", []) or []),
                "blocked_ips": len(policies.get("blocked_ips", []) or []),
                "errors": policies.get("errors", []),
            },
            "pingall": result.get("pingall"),
        }

    def normalize_import_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("El body debe ser un objeto JSON")

        # Permite {"scenario": {...}, "options": {...}} y exports guardados como
        # {"name": "...", "description": "...", "data": {...}, ...}.
        if isinstance(payload.get("scenario"), dict):
            payload = payload["scenario"]
        elif isinstance(payload.get("data"), dict):
            payload = payload["data"]

        if isinstance(payload.get("mininet"), dict):
            mininet = payload["mininet"]
            policies = payload.get("policies", {}) or {}
        elif any(key in payload for key in ("switches", "hosts", "links")):
            mininet = {
                "switches": payload.get("switches", []) or [],
                "hosts": payload.get("hosts", []) or [],
                "links": payload.get("links", []) or [],
            }
            policies = payload.get("policies", {}) or {}
        elif isinstance(payload.get("topology"), dict):
            topology = payload["topology"]
            mininet = self._build_mininet_from_topology(topology)
            policies = payload.get("policies") or self._build_policies_from_topology(topology)
        elif "nodes" in payload and "edges" in payload:
            topology = {"nodes": payload.get("nodes", []), "edges": payload.get("edges", [])}
            mininet = self._build_mininet_from_topology(topology)
            policies = payload.get("policies") or self._build_policies_from_topology(topology)
        else:
            raise ValueError(
                "Formato de topología no reconocido. Usa mininet, switches/hosts/links, topology o nodes/edges."
            )

        # Compatibilidad con exports antiguos o visuales: algunas capturas guardaban
        # el bloqueo en topology.nodes/edges o controller.blocked_ips, pero no en
        # policies.blocked_ips. Al importar, reset_runtime_state() limpia el runtime;
        # por eso hay que reconstruir esta política antes de aplicar el escenario.
        policies = dict(policies or {})
        blocked_ips = set(policies.get("blocked_ips", []) or [])
        blocked_ips.update(self._extract_blocked_ips_from_payload(payload))
        policies["blocked_ips"] = self._normalize_blocked_ips(blocked_ips)

        return {
            "kind": "sdn_topology_scenario",
            "version": int(payload.get("version", 1)),
            "name": payload.get("name") or "web-topology",
            "mininet": {
                "switches": self._normalize_switches(mininet.get("switches", []) or []),
                "hosts": self._normalize_hosts(mininet.get("hosts", []) or []),
                "links": self._normalize_links(mininet.get("links", []) or []),
            },
            "policies": self._normalize_policies(policies),
        }

    def _normalize_switches(self, switches):
        result = []
        for index, switch in enumerate(switches, start=1):
            if not isinstance(switch, dict):
                switch = {"name": str(switch)}

            name = switch.get("name") or switch.get("id") or f"s{index}"
            name = str(name).lower()
            dpid = switch.get("dpid") or self._dpid_from_switch_id(name)

            result.append({
                "name": name,
                "dpid": str(int(str(dpid), 16) if self._looks_hex_dpid(dpid) else int(dpid)),
            })
        return result

    def _normalize_hosts(self, hosts):
        result = []
        for index, host in enumerate(hosts, start=1):
            if not isinstance(host, dict):
                host = {"name": str(host)}

            name = host.get("name") or host.get("id") or f"h{index}"
            ipv4 = list(host.get("ipv4", []) or [])
            ip = host.get("ip") or host.get("ipv4_address") or (ipv4[0] if ipv4 else None)
            if ip and not ipv4:
                ipv4 = [ip]

            normalized = {
                "name": str(name).lower(),
                "mac": host.get("mac"),
                "ip": ip,
                "ipv4": ipv4,
                "ipv6": list(host.get("ipv6", []) or []),
            }

            if host.get("switch"):
                normalized["switch"] = str(host.get("switch")).lower()
            if host.get("switch_dpid") is not None:
                normalized["switch_dpid"] = str(host.get("switch_dpid"))
            if host.get("switch_port") is not None:
                normalized["switch_port"] = int(host.get("switch_port"))

            result.append(normalized)
        return result

    def _normalize_links(self, links):
        result = []
        for link in links:
            if not isinstance(link, dict):
                raise ValueError("Cada link debe ser un objeto JSON")

            src = self._normalize_link_endpoint(link.get("src") or link.get("source"), "src")
            dst = self._normalize_link_endpoint(link.get("dst") or link.get("target"), "dst")
            result.append({
                "type": link.get("type", "switch-link"),
                "src": src,
                "dst": dst,
            })
        return result

    def _normalize_link_endpoint(self, endpoint, name):
        if not isinstance(endpoint, dict):
            raise ValueError(f"{name} de link debe ser objeto JSON")

        node = endpoint.get("node") or endpoint.get("name") or endpoint.get("id")
        dpid = endpoint.get("dpid")
        port_no = endpoint.get("port_no") or endpoint.get("port")

        if dpid is None and node:
            dpid = self._dpid_from_switch_id(node)
        if node is None and dpid is not None:
            node = self._switch_name_from_dpid(dpid)

        result = {
            "node": str(node).lower() if node is not None else None,
            "dpid": str(dpid) if dpid is not None else None,
        }
        if port_no is not None:
            result["port_no"] = int(port_no)
        return result

    def _normalize_policies(self, policies):
        policies = policies or {}
        return {
            "disabled_links": list(policies.get("disabled_links", []) or []),
            "disabled_ports": list(policies.get("disabled_ports", []) or []),
            "tc": list(policies.get("tc", []) or []),
            "blocked_ips": self._normalize_blocked_ips(policies.get("blocked_ips", []) or []),
        }

    def _normalize_blocked_ip_value(self, value):
        text = str(value or "").strip()
        if not text:
            return None

        # Acepta tanto "10.0.0.69" como "10.0.0.69/24" en ficheros viejos.
        try:
            if "/" in text:
                ip = ipaddress.ip_interface(text).ip
            else:
                ip = ipaddress.ip_address(text)
        except Exception:
            # Conserva el valor para que block_ip_traffic() reporte el error exacto
            # en apply_scenario_policies(), en lugar de ocultarlo silenciosamente.
            return text

        return str(ip) if ip.version == 4 else text

    def _normalize_blocked_ips(self, values):
        if values is None:
            return []
        if not isinstance(values, (list, tuple, set)):
            values = [values]

        normalized = []
        seen = set()
        for value in values:
            ip = self._normalize_blocked_ip_value(value)
            if ip and ip not in seen:
                normalized.append(ip)
                seen.add(ip)
        return sorted(normalized)

    def _extract_blocked_ips_from_payload(self, payload):
        blocked = set()
        if not isinstance(payload, dict):
            return blocked

        blocked.update(self._normalize_blocked_ips(payload.get("blocked_ips", [])))

        controller = payload.get("controller") or {}
        if isinstance(controller, dict):
            blocked.update(self._normalize_blocked_ips(controller.get("blocked_ips", [])))

        policies = payload.get("policies") or {}
        if isinstance(policies, dict):
            blocked.update(self._normalize_blocked_ips(policies.get("blocked_ips", [])))

        topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else payload
        if isinstance(topology, dict):
            blocked.update(self._extract_blocked_ips_from_topology(topology))

        return blocked

    def _extract_blocked_ips_from_topology(self, topology):
        blocked = set()
        if not isinstance(topology, dict):
            return blocked

        traffic_filters = topology.get("traffic_filters") or {}
        if isinstance(traffic_filters, dict):
            blocked.update(self._normalize_blocked_ips(traffic_filters.get("blocked_ipv4", [])))

        for node in topology.get("nodes", []) or []:
            if not isinstance(node, dict):
                continue

            filters = node.get("traffic_filters") or {}
            if isinstance(filters, dict):
                blocked.update(self._normalize_blocked_ips(filters.get("blocked_ipv4", [])))

            blocked.update(self._normalize_blocked_ips(node.get("blocked_ipv4", [])))

            if node.get("ip_blocked") or node.get("traffic_blocked") or node.get("traffic_state") == "blocked":
                blocked.update(self._normalize_blocked_ips(node.get("ipv4", [])))
                if node.get("ip"):
                    blocked.update(self._normalize_blocked_ips(node.get("ip")))

        for edge in topology.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            blocked.update(self._normalize_blocked_ips(edge.get("blocked_ipv4", [])))

        return blocked
    
    def _validate_scenario(self, scenario):
        errors = []
        mininet = scenario.get("mininet", {})
        switches = mininet.get("switches", []) or []
        hosts = mininet.get("hosts", []) or []
        links = mininet.get("links", []) or []

        if not switches:
            errors.append("Debe haber al menos un switch")

        switch_names = set()
        switch_dpids = set()
        for switch in switches:
            name = switch.get("name")
            dpid = switch.get("dpid")
            if not name:
                errors.append("Hay un switch sin name")
            if not dpid:
                errors.append(f"El switch {name or '?'} no tiene dpid")
            if name in switch_names:
                errors.append(f"Switch duplicado por name: {name}")
            if dpid in switch_dpids:
                errors.append(f"Switch duplicado por dpid: {dpid}")
            switch_names.add(name)
            switch_dpids.add(str(dpid))

        host_names = set()
        for host in hosts:
            name = host.get("name")
            if not name:
                errors.append("Hay un host sin name")
            if name in host_names:
                errors.append(f"Host duplicado por name: {name}")
            host_names.add(name)

            if host.get("switch") and host.get("switch") not in switch_names:
                errors.append(f"Host {name} conectado a switch inexistente: {host.get('switch')}")

        for index, link in enumerate(links, start=1):
            src = link.get("src", {})
            dst = link.get("dst", {})
            for side_name, endpoint in (("src", src), ("dst", dst)):
                node = endpoint.get("node")
                dpid = endpoint.get("dpid")
                if node and node not in switch_names:
                    errors.append(f"Link {index} {side_name} usa switch inexistente: {node}")
                if dpid and str(dpid) not in switch_dpids:
                    errors.append(f"Link {index} {side_name} usa dpid inexistente: {dpid}")
                if endpoint.get("port_no") is not None and int(endpoint.get("port_no")) <= 0:
                    errors.append(f"Link {index} {side_name} tiene port_no inválido")

        return errors

    def apply_scenario_policies(self, policies):
        policies = policies or {}
        results = {
            "disabled_links": [],
            "disabled_ports": [],
            "tc": [],
            "blocked_ips": [],
            "errors": [],
        }

        for link in policies.get("disabled_links", []) or []:
            try:
                result = self.app.topology_service.disable_link(link["src"], link["dst"])
                results["disabled_links"].append(result)
            except Exception as e:
                results["errors"].append({
                    "policy": "disabled_link",
                    "item": link,
                    "error": str(e),
                })

        for item in policies.get("disabled_ports", []) or []:
            try:
                port = item.get("port", item)
                result = self.app.topology_service.set_port_state(
                    port.get("dpid"),
                    port.get("port_no"),
                    up=False,
                )
                results["disabled_ports"].append(result)
            except Exception as e:
                results["errors"].append({
                    "policy": "disabled_ports",
                    "item": item,
                    "error": str(e),
                })

        for rule in policies.get("tc", []) or []:
            try:
                rule_type = rule.get("type", "link")
                if rule_type == "port":
                    result = self.app.tc_service.update_port_tc(
                        rule["port"],
                        delay=rule.get("delay"),
                        loss=rule.get("loss"),
                        bandwidth=rule.get("bandwidth"),
                    )
                else:
                    result = self.app.tc_service.update_link_tc(
                        rule["src"],
                        rule["dst"],
                        delay=rule.get("delay"),
                        loss=rule.get("loss"),
                        bandwidth=rule.get("bandwidth"),
                    )
                results["tc"].append(result)
            except Exception as e:
                results["errors"].append({
                    "policy": "tc",
                    "item": rule,
                    "error": str(e),
                })

        for ip in policies.get("blocked_ips", []) or []:
            try:
                results["blocked_ips"].append(self.app.block_ip_traffic(ip))
            except Exception as e:
                results["errors"].append({
                    "policy": "blocked_ip",
                    "item": ip,
                    "error": str(e),
                })

        return results

    def wait_until_topology_ready(self, scenario, timeout=40, wait_hosts=False):
        deadline = time.time() + float(timeout)
        expected_switches = {str(sw.get("dpid")) for sw in scenario.get("mininet", {}).get("switches", [])}
        expected_links = self._expected_switch_link_keys(scenario)
        expected_host_count = len(scenario.get("mininet", {}).get("hosts", []) or [])

        last_state = None

        while time.time() < deadline:
            try:
                topology = self.app.topology_service.get_topology_data()
                active_switches = {str(dpid) for dpid in self.app.datapaths.keys()}
                active_links = self._active_switch_link_keys(topology)
                active_hosts = [node for node in topology.get("nodes", []) if node.get("type") == "host"]

                switches_ready = expected_switches.issubset(active_switches)
                links_ready = expected_links.issubset(active_links)
                hosts_ready = True if not wait_hosts else len(active_hosts) >= expected_host_count

                last_state = {
                    "switches_ready": switches_ready,
                    "links_ready": links_ready,
                    "hosts_ready": hosts_ready,
                    "expected_switches": sorted(expected_switches),
                    "active_switches": sorted(active_switches),
                    "expected_links": sorted(list(expected_links)),
                    "active_links": sorted(list(active_links)),
                    "expected_host_count": expected_host_count,
                    "active_host_count": len(active_hosts),
                }

                if switches_ready and links_ready and hosts_ready:
                    last_state["ready"] = True
                    last_state["timeout"] = False
                    return last_state
            except Exception as e:
                last_state = {"ready": False, "error": str(e)}

            hub.sleep(0.5)

        if last_state is None:
            last_state = {}
        last_state["ready"] = False
        last_state["timeout"] = True
        return last_state

    def _expected_switch_link_keys(self, scenario):
        keys = set()
        for link in scenario.get("mininet", {}).get("links", []) or []:
            if link.get("type", "switch-link") != "switch-link":
                continue
            src = link.get("src", {})
            dst = link.get("dst", {})
            if src.get("dpid") is None or dst.get("dpid") is None:
                continue
            if src.get("port_no") is None or dst.get("port_no") is None:
                continue
            keys.add(self._link_key(src["dpid"], src["port_no"], dst["dpid"], dst["port_no"]))
        return keys

    def _active_switch_link_keys(self, topology):
        keys = set()
        for edge in topology.get("edges", []) or []:
            if edge.get("type") != "switch-link":
                continue
            keys.add(self._link_key(
                self._dpid_from_switch_id(edge.get("source")),
                edge.get("src_port"),
                self._dpid_from_switch_id(edge.get("target")),
                edge.get("dst_port"),
            ))
        return keys

    def _link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        a = (str(src_dpid), int(src_port))
        b = (str(dst_dpid), int(dst_port))
        return str(tuple(sorted([a, b])))

    def _post_json(self, url, payload, timeout=40):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    body = json.loads(raw) if raw else None
                except Exception:
                    body = raw

                return {
                    "url": url,
                    "status": getattr(resp, "status", None),
                    "body": body,
                }
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mininet API devolvió HTTP {e.code}: {raw}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"No se pudo conectar con Mininet API en {url}: {e}")

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _dpid_from_switch_id(self, value):
        if value is None:
            raise ValueError("No se pudo inferir dpid de switch vacío")
        text = str(value).strip().lower()
        if text.startswith("s"):
            text = text[1:]
        if text.startswith("0x"):
            return str(int(text, 16))
        return str(int(text))

    def _switch_name_from_dpid(self, dpid):
        return f"s{int(str(dpid), 16) if self._looks_hex_dpid(dpid) else int(dpid)}"

    def _host_name_from_node(self, node):
        name = node.get("name")
        if name:
            return str(name).lower()

        node_id = str(node.get("id", "")).lower()
        if node_id.startswith("h"):
            return node_id

        mac = node.get("mac")
        host_num = self.app.traffic_service._host_number_from_mac(mac) if mac else None
        return f"h{host_num}" if host_num is not None else node_id

    def _natural_name_key(self, name):
        text = str(name or "")
        prefix = "".join(ch for ch in text if not ch.isdigit())
        suffix = "".join(ch for ch in text if ch.isdigit())
        return (prefix, int(suffix) if suffix else 0, text)

    def _looks_hex_dpid(self, dpid):
        text = str(dpid).strip().lower()
        return text.startswith("0x") or any(ch in text for ch in "abcdef")

    def restore_hosts_from_scenario(self, scenario):
        restored = []

        mininet = scenario.get("mininet", {}) or {}
        hosts = mininet.get("hosts", []) or []
        switches = mininet.get("switches", []) or []

        switch_dpid_by_name = {
            str(sw.get("name")).strip().lower(): str(sw.get("dpid"))
            for sw in switches
            if sw.get("name") and sw.get("dpid") is not None
        }

        for host in hosts:
            if not isinstance(host, dict):
                continue

            mac = str(host.get("mac") or "").strip().lower()
            if not mac:
                continue

            name = host.get("name")

            ipv4 = host.get("ipv4")
            if ipv4 is None:
                ipv4 = host.get("ip")

            ipv6 = host.get("ipv6")

            switch_name = host.get("switch")
            switch_name = str(switch_name).strip().lower() if switch_name else None

            switch_dpid = host.get("switch_dpid")
            if switch_dpid is None and switch_name:
                switch_dpid = switch_dpid_by_name.get(switch_name)

            switch_port = host.get("switch_port")

            connected = bool(
                switch_name
                or switch_dpid is not None
                or switch_port is not None
            )

            record = self.app.remember_host(
                mac=mac,
                name=name,
                ipv4=ipv4,
                ipv6=ipv6,
                connected=connected,
                source="scenario",
            )

            # Si está en el escenario importado, no debe seguir marcado como borrado.
            self.app.deleted_host_macs.discard(mac)

            if connected:
                self.app.detached_host_macs.discard(mac)

                if switch_dpid is not None and switch_port is not None:
                    key = (mac, str(switch_dpid), int(switch_port))
                    self.app.host_links_inventory[key] = {
                        "host_mac": mac,
                        "switch": str(switch_dpid),
                        "switch_port": int(switch_port),
                        "enabled": True,
                        "discovered": True,
                        "last_seen": int(time.time()),
                        "source": "scenario",
                        "state": "up",
                        "manual_disabled": False,
                    }
            else:
                self.app.detached_host_macs.add(mac)

                self.app.host_links_inventory = {
                    key: value
                    for key, value in self.app.host_links_inventory.items()
                    if str(value.get("host_mac", "")).strip().lower() != mac
                }

            restored.append({
                "name": record.get("name"),
                "mac": mac,
                "ipv4": record.get("ipv4", []),
                "ipv6": record.get("ipv6", []),
                "connected": connected,
                "state": "connected" if connected else "disconnected",
            })

        return {
            "restored_count": len(restored),
            "restored": restored,
            "deleted_host_macs": sorted(self.app.deleted_host_macs),
            "detached_host_macs": sorted(self.app.detached_host_macs),
        }