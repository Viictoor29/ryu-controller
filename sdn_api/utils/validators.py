import json


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


def normalize_endpoint(endpoint, name="endpoint"):
    if not isinstance(endpoint, dict):
        raise ValueError(f"{name} debe ser un objeto JSON")

    if "dpid" not in endpoint or "port_no" not in endpoint:
        raise ValueError(f"{name} debe incluir 'dpid' y 'port_no'")

    return {
        "dpid": str(endpoint["dpid"]),
        "port_no": int(endpoint["port_no"])
    }