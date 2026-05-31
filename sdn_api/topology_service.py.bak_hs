import re

from rest_helpers import (
    make_link_key,
    normalize_endpoint,
    get_interface_name,
    get_interface_tc_state,
    compute_port_status,
)


class TopologyService:
    def __init__(self, app):
        self.app = app

    def make_link_key(self, src_dpid, src_port, dst_dpid, dst_port):
        return make_link_key(src_dpid, src_port, dst_dpid, dst_port)

    def normalize_endpoint(self, endpoint, name="endpoint"):
        return normalize_endpoint(endpoint, name)

    def get_interface_name(self, dpid, port_no):
        return get_interface_name(dpid, port_no)

    def get_interface_tc_state(self, iface):
        return get_interface_tc_state(iface)

    def compute_port_status(self, stats):
        return compute_port_status(stats)

    def _combine_link_degradation(self, src_status, dst_status):
        if "degraded" in (src_status, dst_status):
            return "degraded"
        if "warning" in (src_status, dst_status):
            return "warning"
        return "healthy"

    def _port_admin_state(self, dpid, port_no):
        return self.app.port_admin_state.get(str(dpid), {}).get(int(port_no), "up")

    def _port_stp_state(self, dpid, port_no):
        return self.app.stp_port_state.get(str(dpid), {}).get(int(port_no))

    def _port_effective_state(self, dpid, port_no, discovered=True, enabled=True):
        admin_state = self._port_admin_state(dpid, port_no)
        stp_state = self._port_stp_state(dpid, port_no)
        blocked = self.app.is_port_blocked(dpid, port_no)

        if not discovered or not enabled or admin_state == "down":
            return "down"

        if stp_state is None:
            return "stp_unknown"

        if blocked or int(stp_state) == 1:
            return "blocked_by_stp"

        if int(stp_state) in (2, 3):
            return "stp_converging"

        return "up"

    def sync_links_inventory(self):
        """
        Sincroniza el inventario con los enlaces descubiertos por Ryu.

        Ryu deja de descubrir un enlace tanto si el cable/enlace ha desaparecido
        como si lo apagamos administrativamente con OFPPortMod. Por eso NO se
        debe interpretar la ausencia en get_link() como borrado físico.

        Regla de negocio:
        - disabled/manual_disabled: apagado desde la API de Ryu, sigue visible.
        - disconnected: Ryu no lo ve ahora mismo, sigue visible como caído.
        - deleted: solo lo marca /api/links/forget, llamado por la API de Mininet.
        """
        valid_keys = set()
        links = self.app.topology_get_links()

        for link in links:
            src_dpid = str(link.src.dpid)
            dst_dpid = str(link.dst.dpid)
            src_port = int(link.src.port_no)
            dst_port = int(link.dst.port_no)

            key = self.make_link_key(src_dpid, src_port, dst_dpid, dst_port)
            valid_keys.add(key)

            current = self.app.links_inventory.setdefault(key, {})

            # Si el enlace fue apagado manualmente pero LLDP todavía lo ve durante
            # unos instantes, no reactivar el inventario hasta que se llame a enable.
            if current.get("manual_disabled") or current.get("state") == "disabled":
                current.update({
                    "source": src_dpid,
                    "target": dst_dpid,
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "enabled": False,
                    "discovered": False,
                    "state": "disabled",
                    "manual_disabled": True,
                })
                continue

            if current.get("state") == "deleted":
                continue

            current.update({
                "source": src_dpid,
                "target": dst_dpid,
                "src_port": src_port,
                "dst_port": dst_port,
                "enabled": True,
                "discovered": True,
                "state": "up",
                "manual_disabled": False,
            })

        for key in list(self.app.links_inventory.keys()):
            if key in valid_keys:
                continue

            link = self.app.links_inventory[key]

            if link.get("state") == "deleted":
                continue

            link["enabled"] = False
            link["discovered"] = False

            if link.get("state") == "disabled" or link.get("manual_disabled"):
                link["state"] = "disabled"
                link["manual_disabled"] = True
            else:
                link["state"] = "disconnected"

    def set_link_inventory_state(self, src, dst, enabled):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        current = self.app.links_inventory.setdefault(key, {
            "source": src["dpid"],
            "target": dst["dpid"],
            "src_port": src["port_no"],
            "dst_port": dst["port_no"],
        })

        current["source"] = src["dpid"]
        current["target"] = dst["dpid"]
        current["src_port"] = src["port_no"]
        current["dst_port"] = dst["port_no"]
        current["enabled"] = bool(enabled)
        current["discovered"] = True
        current["state"] = "up" if enabled else "disabled"
        current["manual_disabled"] = not bool(enabled)

    def forget_link(self, src, dst):
        """
        Elimina un enlace del inventario visual.
        Debe usarse cuando el enlace se borra físicamente de Mininet.
        """
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        key = self.make_link_key(
            src["dpid"], src["port_no"],
            dst["dpid"], dst["port_no"]
        )

        removed = self.app.links_inventory.get(key)
        current = self.app.links_inventory.setdefault(key, {
            "source": src["dpid"],
            "target": dst["dpid"],
            "src_port": src["port_no"],
            "dst_port": dst["port_no"],
        })

        current.update({
            "source": src["dpid"],
            "target": dst["dpid"],
            "src_port": src["port_no"],
            "dst_port": dst["port_no"],
            "enabled": False,
            "discovered": False,
            "manual_disabled": False,
            "state": "deleted",
        })

        return {
            "src": src,
            "dst": dst,
            "removed_from_inventory": removed is not None,
            "hidden_from_topology": True,
            "state": "deleted"
        }
    
    def _set_host_port_inventory_state(self, dpid, port_no, up=True):
        """
        Mantiene coherente el inventario visual de enlaces host-switch cuando
        se cambia administrativamente el estado de un puerto.
        """
        dpid_str = str(dpid)
        port_no = int(port_no)

        for host_link in getattr(self.app, "host_links_inventory", {}).values():
            try:
                matches = (
                    str(host_link.get("switch")) == dpid_str
                    and int(host_link.get("switch_port")) == port_no
                )
            except (TypeError, ValueError):
                continue

            if not matches:
                continue

            host_link["enabled"] = bool(up)

            if up:
                host_link["discovered"] = True
            elif host_link.get("source") in ("mininet", "scenario"):
                # Sigue siendo un enlace esperado/importado; se pinta como down.
                host_link["discovered"] = True
            else:
                host_link["discovered"] = False

    def set_port_state(self, dpid, port_no, up=True):
        dpid = int(dpid)
        port_no = int(port_no)

        datapath = self.app.datapaths.get(dpid)
        if datapath is None:
            raise ValueError(f"No se encontró el switch {dpid}")

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        port = getattr(datapath, "ports", {}).get(port_no)
        if port is None:
            raise ValueError(f"No se encontró el puerto {port_no} en el switch {dpid}")

        config = 0 if up else ofproto.OFPPC_PORT_DOWN
        mask = ofproto.OFPPC_PORT_DOWN

        msg = parser.OFPPortMod(
            datapath=datapath,
            port_no=port_no,
            hw_addr=port.hw_addr,
            config=config,
            mask=mask,
            advertise=0
        )
        datapath.send_msg(msg)

        dpid_str = str(dpid)
        self.app.port_admin_state.setdefault(dpid_str, {})
        self.app.port_admin_state[dpid_str][port_no] = "up" if up else "down"
        self._set_host_port_inventory_state(dpid, port_no, up=up)

        if not up:
            self.app.blocked_ports.discard((dpid, port_no))
            self.app.flush_switch_learning(datapath)

        return {
            "dpid": str(dpid),
            "port_no": port_no,
            "state": "up" if up else "down"
        }

    def disable_link(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        self.set_link_inventory_state(src, dst, enabled=False)

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=False)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=False)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "disabled"
        }

    def enable_link(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=True)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=True)

        self.set_link_inventory_state(src, dst, enabled=True)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "enabled"
        }

    def _host_number_from_mac(self, mac):
        """
        Convención de hosts:
        hN <-> 00:00:00:00:00:NN
        """

        mac = str(mac or "").strip().lower()

        if not re.match(r"^00:00:00:00:00:[0-9a-f]{2}$", mac):
            return None

        try:
            number = int(mac.rsplit(":", 1)[-1], 16)
        except ValueError:
            return None

        if number < 1:
            return None

        return str(number)

    def _host_name_from_mac(self, mac):
        num = self._host_number_from_mac(mac)
        return f"h{num}" if num is not None else None

    def _expected_mac_from_host_name(self, name):
        match = re.match(r"^h(\d+)$", str(name or "").strip().lower())
        if not match:
            return None

        number = int(match.group(1))
        if number < 1 or number > 255:
            return None

        return f"00:00:00:00:00:{number:02x}"


    def _host_matches_name_mac_rule(self, mac, name=None):
        mac = str(mac or "").strip().lower()
        expected_name = self._host_name_from_mac(mac)

        if expected_name is None:
            return False

        if name:
            name = str(name).strip().lower()
            return name == expected_name and self._expected_mac_from_host_name(name) == mac

        return True

    def get_topology_data(self):
        self.sync_links_inventory()

        nodes = []
        edges = []
        seen_nodes = set()

        active_switch_ids = {str(dpid) for dpid in self.app.datapaths.keys()}
        blocked_ipv4_rules = sorted(str(ip) for ip in getattr(self.app, "blocked_ips", set()))

        def normalize_list(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return [str(item) for item in value if item]
            if value:
                return [str(value)]
            return []

        def host_node_suffix(mac):
            host_num = self._host_number_from_mac(mac)
            return host_num if host_num is not None else str(mac)

        def add_host_node(mac, connected=False):
            mac = str(mac or "").strip().lower()
            if not mac or mac in getattr(self.app, "deleted_host_macs", set()):
                return None

            host_record = getattr(self.app, "hosts_inventory", {}).get(mac, {"mac": mac})
            ipv4_list = normalize_list(host_record.get("ipv4"))
            ipv6_list = normalize_list(host_record.get("ipv6"))

            blocked_ips = getattr(self.app, "blocked_ips", set())
            blocked_ipv4 = [ip for ip in ipv4_list if ip in blocked_ips]
            ip_blocked = bool(blocked_ipv4)

            h_id = host_node_suffix(mac)
            node_id = "H" + h_id

            if mac not in seen_nodes:
                nodes.append({
                    "id": node_id,
                    "type": "host",
                    "name": host_record.get("name") or self._host_name_from_mac(mac),
                    "mac": mac,
                    "ipv4": ipv4_list,
                    "ipv6": ipv6_list,
                    "connected": bool(connected),
                    "state": "connected" if connected else "disconnected",
                    "ip_blocked": ip_blocked
                })
                seen_nodes.add(mac)

            return node_id

        try:
            switches = self.app.topology_get_switches()
        except Exception as e:
            self.app.logger.exception("Error obteniendo switches con get_switch(): %s", e)
            switches = []

        for sw in switches:
            sw_id = str(sw.dp.id)

            if sw_id not in active_switch_ids:
                continue

            if sw_id not in seen_nodes:
                nodes.append({
                "id": "S" + sw_id,
                "type": "switch",
                "traffic_filters": {
                    "blocked_ipv4": blocked_ipv4_rules
                }
            })
                seen_nodes.add(sw_id)

        for dpid in sorted(self.app.datapaths.keys()):
            sw_id = str(dpid)

            if sw_id not in seen_nodes:
                nodes.append({
                "id": "S" + sw_id,
                "type": "switch",
                "traffic_filters": {
                    "blocked_ipv4": blocked_ipv4_rules
                }
            })
                seen_nodes.add(sw_id)

        deleted_host_macs = {
            str(mac).strip().lower()
            for mac in getattr(self.app, "deleted_host_macs", set())
        }
        detached_host_macs = {
            str(mac).strip().lower()
            for mac in getattr(self.app, "detached_host_macs", set())
        }

        def is_mininet_known_host(mac):
            mac = str(mac or "").strip().lower()

            host_record = getattr(self.app, "hosts_inventory", {}).get(mac, {})
            if host_record.get("source") == "mininet":
                return True

            return any(
                str(link.get("host_mac", "")).lower() == mac
                and link.get("source") == "mininet"
                for link in getattr(self.app, "host_links_inventory", {}).values()
            )
        
        def drop_invalid_host(mac, reason="invalid_host_name_mac_rule"):
            mac = str(mac or "").strip().lower()
            if not mac:
                return

            self.app.hosts_inventory.pop(mac, None)
            self.app.detached_host_macs.discard(mac)
            self.app.deleted_host_macs.add(mac)
            self.app.host_links_inventory = {
                key: value
                for key, value in self.app.host_links_inventory.items()
                if str(value.get("host_mac", "")).strip().lower() != mac
            }
            self.app.logger.info("Host ignorado por %s: %s", reason, mac)

        try:
            raw_hosts = self.app.topology_get_hosts()
            seen_host_ports = {}
            filtered_hosts = []

            for host in raw_hosts:
                host_mac = str(getattr(host, "mac", "") or "").strip().lower()
                if not host_mac or host_mac in deleted_host_macs:
                    continue

                if not self._host_matches_name_mac_rule(host_mac):
                    drop_invalid_host(host_mac)
                    continue


                ipv4_list = list(host.ipv4) if hasattr(host, "ipv4") else []
                ipv6_list = list(host.ipv6) if hasattr(host, "ipv6") else []

                # Evita hosts fantasma aprendidos por Ryu.
                # Si no tiene IPv4 y no viene de Mininet, no lo guardamos ni lo pintamos.
                if not ipv4_list and not is_mininet_known_host(host_mac):
                    continue

                try:
                    self.app.remember_host(
                        mac=host_mac,
                        name=self._host_name_from_mac(host_mac),
                        ipv4=ipv4_list,
                        ipv6=ipv6_list,
                        connected=host_mac not in detached_host_macs,
                        source="ryu",
                    )
                except Exception:
                    pass

                # Si la API de Mininet nos ha dicho que el h-sw se ha borrado,
                # Ryu puede seguir devolviendo temporalmente un host antiguo.
                # Conservamos el nodo, pero no recreamos el enlace visual stale.
                if host_mac in detached_host_macs:
                    continue

                switch_id = str(host.port.dpid)

                if switch_id not in active_switch_ids:
                    continue

                key = (switch_id, int(host.port.port_no))

                if key not in seen_host_ports:
                    seen_host_ports[key] = host
                    filtered_hosts.append(host)
                    continue

                old = seen_host_ports[key]
                old_ipv4 = list(old.ipv4) if hasattr(old, "ipv4") else []

                # Si hay dos hosts en el mismo puerto, preferimos el que tenga IPv4.
                if ipv4_list and not old_ipv4:
                    filtered_hosts.remove(old)
                    seen_host_ports[key] = host
                    filtered_hosts.append(host)

            hosts = filtered_hosts

        except Exception as e:
            self.app.logger.exception("Error obteniendo hosts con get_host(): %s", e)
            hosts = []

        for key in list(self.app.host_links_inventory.keys()):
            host_link = self.app.host_links_inventory[key]
            host_mac = str(host_link.get("host_mac", "")).lower()

            if host_mac in detached_host_macs:
                self.app.host_links_inventory.pop(key, None)
                continue

            # Los enlaces h-sw declarados por Mininet no deben apagarse solo porque
            # Ryu todavía no haya reaprendido el host. Si no vienen de Mininet,
            # se recalculan con los hosts descubiertos en este ciclo.
            if host_link.get("source") == "mininet":
                continue

            host_link["discovered"] = False
            host_link["enabled"] = False

        for host in hosts:
            host_mac = str(host.mac).lower()

            if host_mac in deleted_host_macs or host_mac in detached_host_macs:
                continue
            
            if not self._host_matches_name_mac_rule(host_mac):
                drop_invalid_host(host_mac)
                continue

            ipv4_list = list(host.ipv4) if hasattr(host, "ipv4") else []
            ipv6_list = list(host.ipv6) if hasattr(host, "ipv6") else []

            try:
                self.app.remember_host(
                    mac=host_mac,
                    name=self._host_name_from_mac(host_mac),
                    ipv4=ipv4_list,
                    ipv6=ipv6_list,
                    connected=True,
                    source="ryu",
                )
            except Exception:
                pass

            switch_id = str(host.port.dpid)

            if switch_id not in active_switch_ids:
                continue

            switch_port = int(host.port.port_no)
            host_link_key = (host_mac, str(switch_id), int(switch_port))

            self.app.host_links_inventory[host_link_key] = {
                "host_mac": host_mac,
                "switch": str(switch_id),
                "switch_port": int(switch_port),
                "enabled": True,
                "discovered": True,
                "source": "ryu"
            }

        # Primero pintamos todos los hosts conocidos, incluidos los desconectados.
        connected_macs = {
            str(link.get("host_mac", "")).lower()
            for link in self.app.host_links_inventory.values()
            if link.get("discovered") and link.get("enabled")
        }

        for mac in sorted(getattr(self.app, "hosts_inventory", {}).keys()):
            if str(mac).lower() in deleted_host_macs:
                continue
            add_host_node(mac, connected=str(mac).lower() in connected_macs)

        # Después pintamos solo los enlaces h-sw que siguen conectados.
        for host_link_key, host_link in list(self.app.host_links_inventory.items()):
            host_mac = str(host_link.get("host_mac", "")).lower()

            if host_mac in deleted_host_macs or host_mac in detached_host_macs:
                continue

            discovered = bool(host_link.get("discovered", False))
            if not discovered:
                continue

            switch_id = str(host_link.get("switch"))
            if switch_id not in active_switch_ids:
                continue

            switch_port = int(host_link.get("switch_port"))
            switch_iface = self.get_interface_name(switch_id, switch_port)
            switch_tc = self.get_interface_tc_state(switch_iface)

            add_host_node(host_mac, connected=True)

            port_stats = self.app.port_stats.get(switch_id, {}).get(switch_port, {})
            port_status = self.compute_port_status(port_stats)

            h_id = host_node_suffix(host_mac)
            admin_state = self._port_admin_state(switch_id, switch_port)
            stp_state = self._port_stp_state(switch_id, switch_port)
            stp_blocked = self.app.is_port_blocked(switch_id, switch_port)

            enabled = (
                bool(host_link.get("enabled", False))
                and admin_state == "up"
                and stp_state != 0
            )

            effective_state = self._port_effective_state(
                switch_id,
                switch_port,
                discovered=discovered,
                enabled=enabled
            )

            if stp_state == 0 and admin_state == "up":
                continue

            edges.append({
                "type": "host-link",
                "source-h": "H" + h_id,
                "mac": host_mac,
                "target-s": "S" + switch_id,
                "s-port": switch_port,
                "s-iface": switch_iface,
                "enabled": enabled,
                "forwarding": effective_state == "up",
                "discovered": discovered,
                "state": effective_state,
                "admin_state": admin_state,
                "stp_state": stp_state,
                "stp_blocked": stp_blocked,
                "tc_sw_port": switch_tc,
                "degradation-link": port_status
            })

        for link in self.app.links_inventory.values():
            inventory_state = link.get("state", "up")

            if inventory_state in ("deleted", "switch_removed"):
                continue

            visible_when_not_discovered = {"disabled", "disconnected", "down"}
            if not link.get("discovered", False) and inventory_state not in visible_when_not_discovered:
                continue

            src_dpid = str(link["source"])
            dst_dpid = str(link["target"])

            if src_dpid not in active_switch_ids or dst_dpid not in active_switch_ids:
                continue

            src_port = int(link["src_port"])
            dst_port = int(link["dst_port"])

            src_iface = self.get_interface_name(src_dpid, src_port)
            dst_iface = self.get_interface_name(dst_dpid, dst_port)

            src_tc = self.get_interface_tc_state(src_iface)
            dst_tc = self.get_interface_tc_state(dst_iface)

            src_stats = self.app.port_stats.get(src_dpid, {}).get(src_port, {})
            dst_stats = self.app.port_stats.get(dst_dpid, {}).get(dst_port, {})

            src_degradation = self.compute_port_status(src_stats)
            dst_degradation = self.compute_port_status(dst_stats)
            link_degradation = self._combine_link_degradation(src_degradation, dst_degradation)

            src_admin = self._port_admin_state(src_dpid, src_port)
            dst_admin = self._port_admin_state(dst_dpid, dst_port)

            src_stp_state = self._port_stp_state(src_dpid, src_port)
            dst_stp_state = self._port_stp_state(dst_dpid, dst_port)

            src_blocked = self.app.is_port_blocked(src_dpid, src_port)
            dst_blocked = self.app.is_port_blocked(dst_dpid, dst_port)

            discovered = bool(link.get("discovered", False))
            inventory_enabled = bool(link.get("enabled", False))

            physical_up = (
                discovered
                and inventory_enabled
                and src_admin == "up"
                and dst_admin == "up"
            )

            src_effective_state = self._port_effective_state(
                src_dpid,
                src_port,
                discovered=discovered,
                enabled=inventory_enabled
            )

            dst_effective_state = self._port_effective_state(
                dst_dpid,
                dst_port,
                discovered=discovered,
                enabled=inventory_enabled
            )

            forwarding = (
                src_effective_state == "up"
                and dst_effective_state == "up"
            )

            if inventory_state == "disabled":
                state = "disabled"
            elif inventory_state == "disconnected":
                state = "disconnected"
            elif src_effective_state == "down" or dst_effective_state == "down":
                state = "down"
            elif "blocked_by_stp" in (src_effective_state, dst_effective_state):
                state = "blocked_by_stp"
            elif "stp_unknown" in (src_effective_state, dst_effective_state):
                state = "stp_unknown"
            elif "stp_converging" in (src_effective_state, dst_effective_state):
                state = "stp_converging"
            else:
                state = "up"

            edges.append({
                "type": "switch-link",
                "source": "S" + src_dpid,
                "target": "S" + dst_dpid,
                "src_port": src_port,
                "dst_port": dst_port,
                "src_iface": src_iface,
                "dst_iface": dst_iface,
                "enabled": physical_up,
                "forwarding": forwarding,
                "discovered": discovered,
                "state": state,
                "inventory_state": inventory_state,
                "manual_disabled": bool(link.get("manual_disabled", False)),
                "admin_state": {
                    "src": src_admin,
                    "dst": dst_admin
                },
                "stp": {
                    "src_state": src_stp_state,
                    "dst_state": dst_stp_state,
                    "src_blocked": src_blocked,
                    "dst_blocked": dst_blocked
                },
                "src_tc": src_tc,
                "dst_tc": dst_tc,
                "src_degradation": src_degradation,
                "dst_degradation": dst_degradation,
                "degradation-link": link_degradation
            })

        return {
            "nodes": nodes,
            "edges": edges
        }
