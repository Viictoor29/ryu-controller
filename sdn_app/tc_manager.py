import subprocess
import re


class TCManager:
    def __init__(self, app):
        self.app = app

    def get_interface_name(self, dpid, port_no):
        return f"s{int(dpid)}-eth{int(port_no)}"

    def normalize_endpoint(self, endpoint, name="endpoint"):
        if not isinstance(endpoint, dict):
            raise ValueError(f"{name} debe ser un objeto JSON")

        if "dpid" not in endpoint or "port_no" not in endpoint:
            raise ValueError(f"{name} debe incluir 'dpid' y 'port_no'")

        return {
            "dpid": str(endpoint["dpid"]),
            "port_no": int(endpoint["port_no"])
        }

    def run_command(self, cmd, timeout=5):
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout
            )
            return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
        except subprocess.TimeoutExpired:
            return 1, "", f"Timeout ejecutando comando: {' '.join(cmd)}"
        except Exception as e:
            return 1, "", str(e)

    def get_interface_tc_state(self, iface):
        result = {
            "delay": None,
            "loss": None,
            "bandwidth": None
        }

        rc, qdisc_out, _ = self.run_command(["sudo", "tc", "qdisc", "show", "dev", iface])

        if rc == 0 and qdisc_out:
            delay_match = re.search(r"\bdelay\s+([0-9]+(?:\.[0-9]+)?[a-zA-Z]+)", qdisc_out)
            if delay_match:
                result["delay"] = delay_match.group(1)

            loss_match = re.search(r"\bloss\s+([0-9]+(?:\.[0-9]+)?)\s*%", qdisc_out)
            if loss_match:
                try:
                    result["loss"] = float(loss_match.group(1))
                except ValueError:
                    result["loss"] = loss_match.group(1)

            bw_match_qdisc = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", qdisc_out)
            if bw_match_qdisc:
                result["bandwidth"] = bw_match_qdisc.group(1)

        rc, class_out, _ = self.run_command(["sudo", "tc", "class", "show", "dev", iface])

        if rc == 0 and class_out:
            bw_match_class = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", class_out)
            if bw_match_class:
                result["bandwidth"] = bw_match_class.group(1)

        return result

    def normalize_bandwidth(self, value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}mbit"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(kbit|mbit|gbit)$", value):
            return value

        raise ValueError("Formato de bandwidth inválido. Usa por ejemplo: 10mbit, 100kbit, 1gbit")

    def normalize_delay(self, value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return f"{value}ms"

        value = str(value).strip().lower()

        if re.match(r"^[0-9]+(?:\.[0-9]+)?(ms|s|us)$", value):
            return value

        raise ValueError("Formato de delay inválido. Usa por ejemplo: 100ms, 1s, 500us")

    def normalize_loss(self, value):
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            raise ValueError("Formato de loss inválido. Usa un número, por ejemplo: 5 o 0.5")

        if value < 0 or value > 100:
            raise ValueError("loss debe estar entre 0 y 100")

        return value

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

        src_result = self.set_interface_tc(
            src_iface,
            delay=delay,
            loss=loss,
            bandwidth=bandwidth
        )

        dst_result = self.set_interface_tc(
            dst_iface,
            delay=delay,
            loss=loss,
            bandwidth=bandwidth
        )

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

        result = self.update_link_tc(
            src, dst,
            delay=current_delay,
            loss=loss,
            bandwidth=current_bw
        )
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

        result = self.update_link_tc(
            src, dst,
            delay=delay,
            loss=current_loss,
            bandwidth=current_bw
        )
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

        result = self.update_link_tc(
            src, dst,
            delay=current_delay,
            loss=current_loss,
            bandwidth=bandwidth
        )
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