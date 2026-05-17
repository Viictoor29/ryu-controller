import re
import time


class MininetHelpersMixin:
    """Funciones auxiliares para DPID, MAC, puertos e interfaces OVS."""

    def endpoint_from_intf(self, intf):
        intf_name = str(intf)
        m = re.match(r"^s(\d+)-eth(\d+)$", intf_name)
        if not m:
            return None
        return {
            "dpid": m.group(1),
            "port_no": int(m.group(2)),
        }

    def port_from_intf(self, intf):
        name = str(intf)
        m = re.match(r"^[a-zA-Z]+\d+-eth(\d+)$", name)
        if m:
            return int(m.group(1))

        try:
            node = intf.node
            return int(node.ports[intf])
        except Exception:
            return None

    def safe_host_mac(self, host):
        try:
            return host.MAC()
        except Exception:
            return None

    def safe_host_ip(self, host):
        try:
            return host.IP()
        except Exception:
            return None

    def mac_from_host_name(self, name):
        m = re.search(r"\d+$", str(name))
        if not m:
            return None
        n = int(m.group())
        if n < 1 or n > 255:
            return None
        return f"00:00:00:00:00:{n:02x}"

    def dpid_from_switch(self, switch):
        for attr in ("dpid", "defaultDpid"):
            value = getattr(switch, attr, None)
            if value:
                try:
                    return str(int(str(value), 16))
                except Exception:
                    try:
                        return str(int(value))
                    except Exception:
                        pass
        return self.dpid_from_name(switch.name)

    def dpid_from_name(self, name):
        m = re.search(r"(\d+)$", str(name))
        if not m:
            raise ValueError(f"No se pudo inferir dpid de {name}")
        return str(int(m.group(1)))

    def switch_name_from_dpid(self, dpid):
        return f"s{int(str(dpid), 16) if self.looks_hex_dpid(dpid) else int(dpid)}"

    def format_dpid(self, dpid):
        value = int(str(dpid), 16) if self.looks_hex_dpid(dpid) else int(dpid)
        return f"{value:016x}"

    def looks_hex_dpid(self, value):
        text = str(value).strip().lower()
        return text.startswith("0x") or bool(re.search(r"[a-f]", text))

    def optional_int(self, value):
        if value is None or value == "":
            return None
        return int(value)

    def get_ovs_ofport(self, switch, intf_name):
        out = switch.cmd(
            "ovs-vsctl",
            "--if-exists",
            "get",
            "Interface",
            intf_name,
            "ofport"
        ).strip()

        try:
            return int(out)
        except Exception:
            return None

    def attach_switch_intf(self, switch, intf, requested_ofport=None):
        intf_name = str(intf)

        if requested_ofport is None:
            switch.attach(intf)
            return {
                "switch": switch.name,
                "intf": intf_name,
                "requested_ofport": None,
                "current_ofport": self.get_ovs_ofport(switch, intf_name)
            }

        requested_ofport = int(requested_ofport)

        # Añadir el puerto a OVS pidiendo explícitamente el OpenFlow port.
        switch.cmd(
            "ovs-vsctl",
            "--may-exist",
            "add-port",
            switch.name,
            intf_name,
            "--",
            "set",
            "Interface",
            intf_name,
            f"ofport_request={requested_ofport}"
        )

        current = None
        for _ in range(20):
            current = self.get_ovs_ofport(switch, intf_name)
            if current == requested_ofport:
                break
            time.sleep(0.1)

        if current != requested_ofport:
            raise RuntimeError(
                f"No se pudo asignar ofport {requested_ofport} a {intf_name}. "
                f"OVS asignó {current}"
            )

        return {
            "switch": switch.name,
            "intf": intf_name,
            "requested_ofport": requested_ofport,
            "current_ofport": current
        }
