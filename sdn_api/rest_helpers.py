from webob import Response

import json
import subprocess
import re
import os
import hmac


API_KEY_HEADER = "X-API-Key"
DEFAULT_NETWORK_API_KEY = "gestordered-tfg-network-api-key-2026"


def get_network_api_key():
    return os.environ.get("NETWORK_API_KEY", DEFAULT_NETWORK_API_KEY)


def authenticated_headers(headers=None, api_key=None):
    result = dict(headers or {})
    network_api_key = api_key if api_key is not None else get_network_api_key()
    if network_api_key:
        result[API_KEY_HEADER] = network_api_key
    return result


def require_api_key(req):
    expected_api_key = get_network_api_key()
    received_api_key = req.headers.get(API_KEY_HEADER, "")

    if not expected_api_key or not hmac.compare_digest(received_api_key, expected_api_key):
        raise PermissionError("No autorizado")


def json_response(data, status=200):
    return Response(
        status=status,
        content_type="application/json",
        charset="utf-8",
        body=json.dumps(data).encode("utf-8"),
        headers=[
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Accept, X-API-Key")
        ]
    )


def cors_preflight():
    return Response(
        status=200,
        headers=[
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Accept, X-API-Key"),
            ("Content-Length", "0")
        ]
    )


def error_response(error, status=400):
    return json_response({
        "ok": False,
        "error": str(error)
    }, status=status)


def success_response(data, status=200):
    return json_response({
        "ok": True,
        "data": data
    }, status=status)


def read_json_body(req):
    if not req.body:
        return {}

    try:
        return json.loads(req.body.decode("utf-8"))
    except Exception:
        raise ValueError("JSON inválido en el body de la petición")


def require_fields(body, *fields):
    missing = [field for field in fields if field not in body]
    if missing:
        raise ValueError(f"Faltan campos obligatorios: {', '.join(missing)}")


def make_link_key(src_dpid, src_port, dst_dpid, dst_port):
    a = (str(src_dpid), int(src_port))
    b = (str(dst_dpid), int(dst_port))
    return tuple(sorted([a, b]))


def normalize_endpoint(endpoint, name="endpoint"):
    if not isinstance(endpoint, dict):
        raise ValueError(f"{name} debe ser un objeto JSON")

    if "dpid" not in endpoint or "port_no" not in endpoint:
        raise ValueError(f"{name} debe incluir 'dpid' y 'port_no'")

    return {
        "dpid": str(endpoint["dpid"]),
        "port_no": int(endpoint["port_no"])
    }


def empty_speed():
    return {
        "bps": 0,
        "kbps": 0,
        "mbps": 0
    }


def compute_port_status(
    stats,
    drop_threshold=10,
    drop_ratio_threshold=0.01,
):
    """
    Estado lógico del puerto.

    - degraded: hay errores reales.
    - warning: hay pérdidas significativas.
    - healthy: sin errores, o solo drops pequeños/transitorios.

    Esto evita marcar como warning enlaces recién creados por 1-2 drops
    producidos durante STP/LLDP/ARP/convergencia inicial.
    """
    rx_errors = stats.get("rx_errors", 0)
    tx_errors = stats.get("tx_errors", 0)
    rx_dropped = stats.get("rx_dropped", 0)
    tx_dropped = stats.get("tx_dropped", 0)
    rx_packets = stats.get("rx_packets", 0)
    tx_packets = stats.get("tx_packets", 0)

    total_errors = rx_errors + tx_errors
    total_drops = rx_dropped + tx_dropped
    total_packets = rx_packets + tx_packets

    if total_errors > 0:
        return "degraded"

    if total_drops <= 0:
        return "healthy"

    # Ignorar drops pequeños típicos al crear enlaces/switches.
    if total_drops < drop_threshold:
        return "healthy"

    # Si hay mucho tráfico y el porcentaje de drops es insignificante,
    # tampoco lo marcamos como warning.
    if total_packets > 0:
        drop_ratio = total_drops / max(total_packets + total_drops, 1)
        if drop_ratio < drop_ratio_threshold:
            return "healthy"

    return "warning"


def compute_overall_status(degraded_switches, warning_switches, degraded_ports, warning_ports):
    if degraded_switches > 0 or degraded_ports > 0:
        return "degraded"
    if warning_switches > 0 or warning_ports > 0:
        return "warning"
    return "healthy"


def get_interface_name(dpid, port_no):
    return f"s{int(dpid)}-eth{int(port_no)}"


def run_command(cmd, timeout=5):
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


def get_interface_tc_state(iface):
    result = {
        "delay": None,
        "loss": None,
        "bandwidth": None
    }

    rc, qdisc_out, _ = run_command(["sudo", "tc", "qdisc", "show", "dev", iface])

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

    rc, class_out, _ = run_command(["sudo", "tc", "class", "show", "dev", iface])

    if rc == 0 and class_out:
        bw_match_class = re.search(r"\brate\s+([0-9]+(?:\.[0-9]+)?[KMG]bit)", class_out)
        if bw_match_class:
            result["bandwidth"] = bw_match_class.group(1)

    return result


def normalize_bandwidth(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return f"{value}mbit"

    value = str(value).strip().lower()

    if re.match(r"^[0-9]+(?:\.[0-9]+)?(kbit|mbit|gbit)$", value):
        return value

    raise ValueError("Formato de bandwidth inválido. Usa por ejemplo: 10mbit, 100kbit, 1gbit")


def normalize_delay(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return f"{value}ms"

    value = str(value).strip().lower()

    if re.match(r"^[0-9]+(?:\.[0-9]+)?(ms|s|us)$", value):
        return value

    raise ValueError("Formato de delay inválido. Usa por ejemplo: 100ms, 1s, 500us")


def normalize_loss(value):
    if value is None:
        return None

    try:
        value = float(value)
    except Exception:
        raise ValueError("Formato de loss inválido. Usa un número, por ejemplo: 5 o 0.5")

    if value < 0 or value > 100:
        raise ValueError("loss debe estar entre 0 y 100")

    return value