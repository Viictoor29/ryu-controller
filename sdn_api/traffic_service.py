import re
import time
import subprocess

from rest_helpers import run_command


class TrafficService:
    def __init__(self, app):
        self.app = app

    def _run_command(self, cmd, timeout=10):
        return run_command(cmd, timeout)
    
    def _host_number_from_mac(self, mac):
        mac = str(mac).strip().lower()
        parts = mac.split(":")
        if len(parts) != 6:
            return None
        try:
            return str(int(parts[-1], 16))
        except ValueError:
            return None

    def _host_name_from_mac(self, mac):
        num = self._host_number_from_mac(mac)
        return f"h{num}" if num is not None else None

    def _find_host(self, host_ref):
        hosts = self.app.topology_get_hosts()

        def build_host_data(host, fallback_name=None):
            mac = str(getattr(host, "mac", ""))
            ipv4_list = list(getattr(host, "ipv4", []))
            ipv6_list = list(getattr(host, "ipv6", []))

            inferred_name = self._host_name_from_mac(mac)

            return {
                "name": fallback_name or inferred_name,
                "mac": mac,
                "ipv4": ipv4_list,
                "ipv6": ipv6_list,
            }

        if isinstance(host_ref, str):
            value = host_ref.strip()

            for host in hosts:
                mac = str(getattr(host, "mac", ""))
                ipv4_list = list(getattr(host, "ipv4", []))
                ipv6_list = list(getattr(host, "ipv6", []))

                if value == mac or value in ipv4_list or value in ipv6_list:
                    return build_host_data(host)

            if re.match(r"^[a-zA-Z]+\d+$", value):
                idx_match = re.search(r"(\d+)$", value)
                if idx_match:
                    wanted_num = idx_match.group(1)

                    for host in hosts:
                        mac = str(getattr(host, "mac", ""))
                        host_num = self._host_number_from_mac(mac)
                        if host_num == wanted_num:
                            return build_host_data(host, fallback_name=value)

                return {
                    "name": value,
                    "mac": None,
                    "ipv4": [],
                    "ipv6": [],
                }

            raise ValueError(f"No se pudo resolver el host '{value}'")

        if not isinstance(host_ref, dict):
            raise ValueError("La referencia del host debe ser string u objeto JSON")

        name = host_ref.get("name")
        mac = host_ref.get("mac")
        ipv4 = host_ref.get("ipv4")
        ipv6 = host_ref.get("ipv6")

        if name:
            value = str(name).strip()

            if re.match(r"^[a-zA-Z]+\d+$", value):
                idx_match = re.search(r"(\d+)$", value)
                if idx_match:
                    wanted_num = idx_match.group(1)

                    for host in hosts:
                        host_mac = str(getattr(host, "mac", ""))
                        host_num = self._host_number_from_mac(host_mac)
                        if host_num == wanted_num:
                            return build_host_data(host, fallback_name=value)

            return {
                "name": value,
                "mac": None,
                "ipv4": [],
                "ipv6": [],
            }

        for host in hosts:
            host_mac = str(getattr(host, "mac", ""))
            host_ipv4 = list(getattr(host, "ipv4", []))
            host_ipv6 = list(getattr(host, "ipv6", []))

            if mac and str(mac) == host_mac:
                return build_host_data(host)

            if ipv4 and str(ipv4) in host_ipv4:
                return build_host_data(host)

            if ipv6 and str(ipv6) in host_ipv6:
                return build_host_data(host)

        raise ValueError("No se encontró el host indicado")

    def _host_target_ip(self, host_data):
        if host_data.get("ipv4"):
            return host_data["ipv4"][0]
        if host_data.get("ipv6"):
            return host_data["ipv6"][0]
        raise ValueError("El host destino no tiene IP descubierta")

    def _host_exec_name(self, host_data):
        """
        Para ejecutar en Mininet necesitamos normalmente el nombre del host, ej: h1.
        """
        if host_data.get("name"):
            return host_data["name"]
        raise ValueError(
            "No se puede ejecutar sobre el host porque no tiene 'name'. "
            "Pasa src_host/dst_host como {'name': 'h1'} por ejemplo."
        )

    def _get_host_pid(self, host_name):
        rc, out, err = self._run_command(
            ["bash", "-lc", f"ps -eo pid,args | grep 'mininet:{host_name}$' | grep -v grep | awk '{{print $1}}' | head -n 1"],
            timeout=5
        )

        if rc != 0 or not out.strip():
            raise RuntimeError(
                f"No se encontró el namespace del host {host_name}. "
                f"Asegúrate de estar ejecutando esto en un entorno Mininet activo."
            )

        return out.strip()

    def _exec_in_host(self, host_name, cmd, timeout=10):
        pid = self._get_host_pid(host_name)
        full_cmd = ["sudo", "mnexec", "-a", pid] + cmd
        return self._run_command(full_cmd, timeout=timeout)

    def generate_ping(self, src_host, dst_host, count=4, interval=0.2, timeout=10):
        src = self._find_host(src_host)
        dst = self._find_host(dst_host)

        src_name = self._host_exec_name(src)
        dst_ip = self._host_target_ip(dst)

        cmd = [
            "ping",
            "-c", str(int(count)),
            "-i", str(float(interval)),
            dst_ip
        ]

        rc, out, err = self._exec_in_host(src_name, cmd, timeout=timeout)

        transmitted = None
        received = None
        loss = None
        rtt_min = None
        rtt_avg = None
        rtt_max = None
        rtt_mdev = None

        m = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+received,\s+([0-9.]+)%\s+packet loss", out)
        if m:
            transmitted = int(m.group(1))
            received = int(m.group(2))
            loss = float(m.group(3))

        m = re.search(r"=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms", out)
        if m:
            rtt_min = float(m.group(1))
            rtt_avg = float(m.group(2))
            rtt_max = float(m.group(3))
            rtt_mdev = float(m.group(4))

        return {
            "src_host": src_name,
            "dst_ip": dst_ip,
            "command": " ".join(cmd),
            "return_code": rc,
            "success": rc == 0,
            "stats": {
                "transmitted": transmitted,
                "received": received,
                "packet_loss_percent": loss,
                "rtt_min_ms": rtt_min,
                "rtt_avg_ms": rtt_avg,
                "rtt_max_ms": rtt_max,
                "rtt_mdev_ms": rtt_mdev
            },
            "stdout": out,
            "stderr": err
        }

    def _start_iperf_server(self, dst_name, udp=False, port=5201):
        cmd = ["bash", "-lc", f"nohup iperf {'-u' if udp else ''} -s -p {int(port)} >/tmp/iperf_server_{dst_name}_{port}.log 2>&1 & echo $!"]
        rc, out, err = self._exec_in_host(dst_name, cmd, timeout=5)
        if rc != 0 or not out.strip():
            raise RuntimeError(f"No se pudo arrancar iperf server en {dst_name}: {err or out}")
        return out.strip()

    def _stop_iperf_server(self, dst_name, server_pid):
        try:
            self._exec_in_host(dst_name, ["kill", "-9", str(server_pid)], timeout=5)
        except Exception:
            pass

    def generate_iperf(self, src_host, dst_host, duration=10, udp=False, bandwidth=None, port=5201, timeout=20):
        src = self._find_host(src_host)
        dst = self._find_host(dst_host)

        src_name = self._host_exec_name(src)
        dst_name = self._host_exec_name(dst)
        dst_ip = self._host_target_ip(dst)

        server_pid = self._start_iperf_server(dst_name, udp=udp, port=port)
        time.sleep(1)

        try:
            cmd = ["iperf", "-c", dst_ip, "-p", str(int(port)), "-t", str(int(duration))]
            if udp:
                cmd.append("-u")
                if bandwidth:
                    cmd += ["-b", str(bandwidth)]

            rc, out, err = self._exec_in_host(src_name, cmd, timeout=timeout)

            bandwidth_match = re.findall(r"([0-9.]+\s+[KMG]bits/sec)", out)
            transfer_match = re.findall(r"([0-9.]+\s+[KMG]Bytes)", out)

            jitter_match = re.search(r"([0-9.]+)\s+ms\s+\d+/\s*\d+\s+\(([0-9.]+)%\)", out)

            return {
                "src_host": src_name,
                "dst_host": dst_name,
                "dst_ip": dst_ip,
                "command": " ".join(cmd),
                "return_code": rc,
                "success": rc == 0,
                "udp": bool(udp),
                "duration_seconds": int(duration),
                "port": int(port),
                "bandwidth_requested": bandwidth if udp else None,
                "result": {
                    "transfer": transfer_match[-1] if transfer_match else None,
                    "bandwidth": bandwidth_match[-1] if bandwidth_match else None,
                    "jitter_ms": float(jitter_match.group(1)) if jitter_match else None,
                    "loss_percent": float(jitter_match.group(2)) if jitter_match else None
                },
                "stdout": out,
                "stderr": err
            }
        finally:
            self._stop_iperf_server(dst_name, server_pid)