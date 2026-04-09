from ryu.app.wsgi import ControllerBase, route
from webob import Response
import json


API_INSTANCE_NAME = "sdn_api_app"


class SDNRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SDNRestController, self).__init__(req, link, data, **config)
        self.sdn_app = data[API_INSTANCE_NAME]

    def json_response(self, data, status=200):
        return Response(
            status=status,
            content_type="application/json",
            charset="utf-8",
            body=json.dumps(data).encode("utf-8"),
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, Accept")
            ]
        )

    def cors_preflight(self):
        return Response(
            status=200,
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, Accept"),
                ("Content-Length", "0")
            ]
        )

    def error_response(self, error, status=400):
        return self.json_response({
            "ok": False,
            "error": str(error)
        }, status=status)

    def success_response(self, data, status=200):
        return self.json_response({
            "ok": True,
            "data": data
        }, status=status)

    def read_json_body(self, req):
        if not req.body:
            return {}

        try:
            return json.loads(req.body.decode("utf-8"))
        except Exception:
            raise ValueError("JSON inválido en el body de la petición")

    def require_fields(self, body, *fields):
        missing = [field for field in fields if field not in body]
        if missing:
            raise ValueError(f"Faltan campos obligatorios: {', '.join(missing)}")

    @route("topology", "/api/topology", methods=["GET", "OPTIONS"])
    def get_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.topology_service.get_topology_data()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/topology: %s", e)
            return self.error_response(e, status=500)

    @route("disable_link", "/api/links/disable", methods=["POST", "OPTIONS"])
    def disable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.topology_service.disable_link(
                body["src"],
                body["dst"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/disable: %s", e)
            return self.error_response(e, status=400)

    @route("enable_link", "/api/links/enable", methods=["POST", "OPTIONS"])
    def enable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.topology_service.enable_link(
                body["src"],
                body["dst"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/enable: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_loss", "/api/links/loss", methods=["POST", "OPTIONS"])
    def set_link_loss(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "loss")

            result = self.sdn_app.tc_manager.set_link_loss(
                body["src"],
                body["dst"],
                body["loss"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/loss: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_bandwidth", "/api/links/bandwidth", methods=["POST", "OPTIONS"])
    def set_link_bandwidth(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "bandwidth")

            result = self.sdn_app.tc_manager.set_link_bandwidth(
                body["src"],
                body["dst"],
                body["bandwidth"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/bandwidth: %s", e)
            return self.error_response(e, status=400)

    @route("set_link_delay", "/api/links/delay", methods=["POST", "OPTIONS"])
    def set_link_delay(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst", "delay")

            result = self.sdn_app.tc_manager.set_link_delay(
                body["src"],
                body["dst"],
                body["delay"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/delay: %s", e)
            return self.error_response(e, status=400)

    @route("clear_link_tc", "/api/links/tc/clear", methods=["POST", "OPTIONS"])
    def clear_link_tc(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.read_json_body(req)
            self.require_fields(body, "src", "dst")

            result = self.sdn_app.tc_manager.clear_link_tc(
                body["src"],
                body["dst"]
            )
            return self.success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/tc/clear: %s", e)
            return self.error_response(e, status=400)

    @route("controller_status", "/api/controller/status", methods=["GET", "OPTIONS"])
    def get_controller_status(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.topology_service.get_controller_status()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/controller/status: %s", e)
            return self.error_response(e, status=500)

    @route("health_metrics", "/api/health", methods=["GET", "OPTIONS"])
    def get_health_metrics(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.health_service.get_health_metrics()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health: %s", e)
            return self.error_response(e, status=500)

    @route("health_summary", "/api/health/summary", methods=["GET", "OPTIONS"])
    def get_health_summary(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            body = self.sdn_app.health_service.get_health_summary()
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health/summary: %s", e)
            return self.error_response(e, status=500)

    @route("switch_ports", "/api/switch/{dpid}/ports", methods=["GET", "OPTIONS"])
    def get_switch_ports(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.health_service.get_switch_ports(dpid)
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/ports: %s", kwargs.get("dpid"), e)
            return self.error_response(e, status=500)

    @route("switch_flows", "/api/switch/{dpid}/flows", methods=["GET", "OPTIONS"])
    def get_switch_flows(self, req, **kwargs):
        if req.method == "OPTIONS":
            return self.cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.health_service.get_switch_flows(dpid)
            return self.success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/flows: %s", kwargs.get("dpid"), e)
            return self.error_response(e, status=500)