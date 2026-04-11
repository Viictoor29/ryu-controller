from rest_helpers import (
    normalize_endpoint,
    get_interface_name,
    run_command,
    get_interface_tc_state,
    normalize_bandwidth,
    normalize_delay,
    normalize_loss,
)


class TCService:
    def __init__(self, app):
        self.app = app

    def normalize_endpoint(self, endpoint, name="endpoint"):
        return normalize_endpoint(endpoint, name)

    def get_interface_name(self, dpid, port_no):
        return get_interface_name(dpid, port_no)

    def run_command(self, cmd, timeout=5):
        return run_command(cmd, timeout)

    def get_interface_tc_state(self, iface):
        return get_interface_tc_state(iface)

    def normalize_bandwidth(self, value):
        return normalize_bandwidth(value)

    def normalize_delay(self, value):
        return normalize_delay(value)

    def normalize_loss(self, value):
        return normalize_loss(value)

    def clear_interface_tc(self, iface):
        rc, out, err = self.run_command(["sudo", "tc", "qdisc", "del", "dev", iface, "root"])

        if rc != 0:
            error_text = (err or out).lower()
            if "no such file" in error_text or "cannot find device" in error_text:
                raise RuntimeError(f"La interfaz {iface} no existe")
            if "noqueue" in error_text or "no qdisc" in error_text or "not found" in error_text:
                return
            if "operation not permitted" in error_text or "permission denied" in error_text:
                raise RuntimeError(
                    f"No hay permisos para ejecutar tc sobre {iface}. "
                    f"Configura sudo sin password para el comando tc."
                )

    def set_interface_tc(self, iface, delay=None, loss=None, bandwidth=None):
        delay = self.normalize_delay(delay) if delay is not None else None
        loss = self.normalize_loss(loss) if loss is not None else None
        bandwidth = self.normalize_bandwidth(bandwidth) if bandwidth is not None else None

        args = ["sudo", "tc", "qdisc", "replace", "dev", iface, "root", "netem"]
        has_any = False

        if delay is not None:
            args += ["delay", delay]
            has_any = True

        if loss is not None:
            args += ["loss", f"{loss}%"]
            has_any = True

        if bandwidth is not None:
            args += ["rate", bandwidth]
            has_any = True

        if not has_any:
            self.clear_interface_tc(iface)
            return {
                "iface": iface,
                "delay": None,
                "loss": None,
                "bandwidth": None
            }

        rc, out, err = self.run_command(args)
        if rc != 0:
            error_text = err or out

            if "operation not permitted" in error_text.lower() or "permission denied" in error_text.lower():
                raise RuntimeError(
                    f"No hay permisos para ejecutar tc sobre {iface}. "
                    f"Configura sudo sin password para el comando tc."
                )

            if "cannot find device" in error_text.lower() or "no such file" in error_text.lower():
                raise RuntimeError(f"La interfaz {iface} no existe")

            raise RuntimeError(f"Error aplicando tc en {iface}: {error_text}")

        state = self.get_interface_tc_state(iface)
        return {
            "iface": iface,
            "delay": state["delay"],
            "loss": state["loss"],
            "bandwidth": state["bandwidth"]
        }

    def update_link_tc(self, src, dst, delay=None, loss=None, bandwidth=None):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_result = self.set_interface_tc(src_iface, delay=delay, loss=loss, bandwidth=bandwidth)
        dst_result = self.set_interface_tc(dst_iface, delay=delay, loss=loss, bandwidth=bandwidth)

        return {
            "src": {
                "dpid": src["dpid"],
                "port_no": src["port_no"],
                **src_result
            },
            "dst": {
                "dpid": dst["dpid"],
                "port_no": dst["port_no"],
                **dst_result
            }
        }

    def set_link_loss(self, src, dst, loss):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(src, dst, delay=current_delay, loss=loss, bandwidth=current_bw)
        result["link_state"] = "loss_updated"
        return result

    def set_link_delay(self, src, dst, delay):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]
        current_bw = src_current["bandwidth"] or dst_current["bandwidth"]

        result = self.update_link_tc(src, dst, delay=delay, loss=current_loss, bandwidth=current_bw)
        result["link_state"] = "delay_updated"
        return result

    def set_link_bandwidth(self, src, dst, bandwidth):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        src_current = self.get_interface_tc_state(src_iface)
        dst_current = self.get_interface_tc_state(dst_iface)

        current_delay = src_current["delay"] or dst_current["delay"]
        current_loss = src_current["loss"] if src_current["loss"] is not None else dst_current["loss"]

        result = self.update_link_tc(src, dst, delay=current_delay, loss=current_loss, bandwidth=bandwidth)
        result["link_state"] = "bandwidth_updated"
        return result

    def clear_link_tc(self, src, dst):
        src = self.normalize_endpoint(src, "src")
        dst = self.normalize_endpoint(dst, "dst")

        src_iface = self.get_interface_name(src["dpid"], src["port_no"])
        dst_iface = self.get_interface_name(dst["dpid"], dst["port_no"])

        self.clear_interface_tc(src_iface)
        self.clear_interface_tc(dst_iface)

        return {
            "src": {
                "dpid": src["dpid"],
                "port_no": src["port_no"],
                "iface": src_iface
            },
            "dst": {
                "dpid": dst["dpid"],
                "port_no": dst["port_no"],
                "iface": dst_iface
            },
            "link_state": "tc_cleared"
        }