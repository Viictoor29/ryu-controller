from ryu.app.wsgi import ControllerBase, route

from rest_helpers import (
    cors_preflight,
    error_response,
    success_response,
    read_json_body,
    require_fields,
)

API_INSTANCE_NAME = "sdn_api_app"


class SDNRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SDNRestController, self).__init__(req, link, data, **config)
        self.sdn_app = data[API_INSTANCE_NAME]

    @route("topology", "/api/topology", methods=["GET", "OPTIONS"])
    def get_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = self.sdn_app.topology_service.get_topology_data()
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/topology: %s", e)
            return error_response(e, status=500)

    @route("disable_link", "/api/links/disable", methods=["POST", "OPTIONS"])
    def disable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst")

            result = self.sdn_app.topology_service.disable_link(body["src"], body["dst"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/disable: %s", e)
            return error_response(e, status=400)

    @route("enable_link", "/api/links/enable", methods=["POST", "OPTIONS"])
    def enable_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst")

            result = self.sdn_app.topology_service.enable_link(body["src"], body["dst"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/enable: %s", e)
            return error_response(e, status=400)

    @route("set_link_loss", "/api/links/loss", methods=["POST", "OPTIONS"])
    def set_link_loss(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst", "loss")

            result = self.sdn_app.tc_service.set_link_loss(body["src"], body["dst"], body["loss"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/loss: %s", e)
            return error_response(e, status=400)

    @route("set_link_bandwidth", "/api/links/bandwidth", methods=["POST", "OPTIONS"])
    def set_link_bandwidth(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst", "bandwidth")

            result = self.sdn_app.tc_service.set_link_bandwidth(body["src"], body["dst"], body["bandwidth"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/bandwidth: %s", e)
            return error_response(e, status=400)

    @route("set_link_delay", "/api/links/delay", methods=["POST", "OPTIONS"])
    def set_link_delay(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst", "delay")

            result = self.sdn_app.tc_service.set_link_delay(body["src"], body["dst"], body["delay"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/delay: %s", e)
            return error_response(e, status=400)

    @route("clear_link_tc", "/api/links/tc/clear", methods=["POST", "OPTIONS"])
    def clear_link_tc(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst")

            result = self.sdn_app.tc_service.clear_link_tc(body["src"], body["dst"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/tc/clear: %s", e)
            return error_response(e, status=400)

    @route("controller_status", "/api/controller/status", methods=["GET", "OPTIONS"])
    def get_controller_status(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = self.sdn_app.health_service.get_controller_status()
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/controller/status: %s", e)
            return error_response(e, status=500)

    @route("health_metrics", "/api/health", methods=["GET", "OPTIONS"])
    def get_health_metrics(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = self.sdn_app.health_service.get_health_metrics()
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health: %s", e)
            return error_response(e, status=500)

    @route("health_summary", "/api/health/summary", methods=["GET", "OPTIONS"])
    def get_health_summary(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = self.sdn_app.health_service.get_health_summary()
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/health/summary: %s", e)
            return error_response(e, status=500)

    @route("switch_ports", "/api/switch/{dpid}/ports", methods=["GET", "OPTIONS"])
    def get_switch_ports(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.health_service.get_switch_ports(dpid)
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/ports: %s", kwargs.get("dpid"), e)
            return error_response(e, status=500)

    @route("switch_flows", "/api/switch/{dpid}/flows", methods=["GET", "OPTIONS"])
    def get_switch_flows(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            dpid = kwargs["dpid"]
            body = self.sdn_app.health_service.get_switch_flows(dpid)
            return success_response(body)
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/switch/%s/flows: %s", kwargs.get("dpid"), e)
            return error_response(e, status=500)