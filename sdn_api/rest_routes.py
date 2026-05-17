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

    @route("topology_export", "/api/topology/export", methods=["GET", "OPTIONS"])
    def export_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            name = req.GET.get("name") if hasattr(req, "GET") else None
            include_runtime = False
            include_controller = False

            if hasattr(req, "GET") and req.GET.get("include_runtime") is not None:
                include_runtime = str(req.GET.get("include_runtime")).lower() in ("1", "true", "yes")

            if hasattr(req, "GET") and req.GET.get("include_controller") is not None:
                include_controller = str(req.GET.get("include_controller")).lower() in ("1", "true", "yes")

            body = self.sdn_app.scenario_service.export_current_topology(
                name=name,
                include_runtime=include_runtime,
                include_controller=include_controller,
            )

            return success_response(body)

        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/topology/export: %s", e)
        return error_response(e, status=500)

    @route("topology_validate", "/api/topology/validate", methods=["POST", "OPTIONS"])
    def validate_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            result = self.sdn_app.scenario_service.validate_import_payload(body)
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/topology/validate: %s", e)
            return error_response(e, status=400)

    @route("topology_import", "/api/topology/import", methods=["POST", "OPTIONS"])
    def import_topology(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            result = self.sdn_app.scenario_service.import_topology_from_web(body)
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/topology/import: %s", e)
            return error_response(e, status=400)

    @route("controller_runtime_reset", "/api/controller/runtime/reset", methods=["POST", "OPTIONS"])
    def reset_runtime_state(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            result = self.sdn_app.reset_runtime_state(
                preserve_blocked_ips=body.get("preserve_blocked_ips", False),
                flush_flows=body.get("flush_flows", True),
                clear_deleted_hosts=body.get("clear_deleted_hosts", False),
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/controller/runtime/reset: %s", e)
            return error_response(e, status=400)

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

    @route("set_port_loss", "/api/ports/loss", methods=["POST", "OPTIONS"])
    def set_port_loss(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "port", "loss")

            result = self.sdn_app.tc_service.set_port_loss(body["port"], body["loss"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/loss: %s", e)
            return error_response(e, status=400)

    @route("set_port_bandwidth", "/api/ports/bandwidth", methods=["POST", "OPTIONS"])
    def set_port_bandwidth(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "port", "bandwidth")

            result = self.sdn_app.tc_service.set_port_bandwidth(body["port"], body["bandwidth"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/bandwidth: %s", e)
            return error_response(e, status=400)

    @route("set_port_delay", "/api/ports/delay", methods=["POST", "OPTIONS"])
    def set_port_delay(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "port", "delay")

            result = self.sdn_app.tc_service.set_port_delay(body["port"], body["delay"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/delay: %s", e)
            return error_response(e, status=400)

    @route("clear_port_tc", "/api/ports/tc/clear", methods=["POST", "OPTIONS"])
    def clear_port_tc(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "port")

            result = self.sdn_app.tc_service.clear_port_tc(body["port"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/tc/clear: %s", e)
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
    
    @route("traffic_block_ip", "/api/traffic/block-ip", methods=["POST", "OPTIONS"])
    def traffic_block_ip(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "ip")

            result = self.sdn_app.block_ip_traffic(body["ip"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/block-ip: %s", e)
            return error_response(e, status=400)

    @route("traffic_unblock_ip", "/api/traffic/unblock-ip", methods=["POST", "OPTIONS"])
    def traffic_unblock_ip(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "ip")

            result = self.sdn_app.unblock_ip_traffic(body["ip"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/unblock-ip: %s", e)
            return error_response(e, status=400)

    @route("traffic_unblock_all_ips", "/api/traffic/unblock-all-ips", methods=["POST", "OPTIONS"])
    def traffic_unblock_all_ips(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            result = self.sdn_app.unblock_all_ip_traffic()
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/unblock-all-ips: %s", e)
            return error_response(e, status=400)

    @route("traffic_blocked_ips", "/api/traffic/blocked-ips", methods=["GET", "OPTIONS"])
    def traffic_blocked_ips(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            return success_response(self.sdn_app.get_blocked_ips_status())
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/traffic/blocked-ips: %s", e)
            return error_response(e, status=500)

    @route("traffic_ping", "/api/traffic/ping", methods=["POST", "OPTIONS"])
    def traffic_ping(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src_host", "dst_host")

            result = self.sdn_app.traffic_service.generate_ping(
                src_host=body["src_host"],
                dst_host=body["dst_host"],
                count=body.get("count", 4),
                interval=body.get("interval", 0.2),
                timeout=body.get("timeout", 10)
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/ping: %s", e)
            return error_response(e, status=400)


    @route("traffic_pingall", "/api/traffic/pingall", methods=["POST", "OPTIONS"])
    def traffic_pingall(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)

            result = self.sdn_app.traffic_service.generate_pingall(
                count=body.get("count", 1),
                interval=body.get("interval", 0.2),
                timeout_per_ping=body.get("timeout_per_ping", 5)
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/pingall: %s", e)
            return error_response(e, status=400)

    @route("stp_status", "/api/stp/status", methods=["GET", "OPTIONS"])
    def stp_status(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            return success_response(self.sdn_app.get_stp_status())
        except Exception as e:
            self.sdn_app.logger.exception("Error en GET /api/stp/status: %s", e)
            return error_response(e, status=500)

    @route("traffic_iperf", "/api/traffic/iperf", methods=["POST", "OPTIONS"])
    def traffic_iperf(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src_host", "dst_host")

            result = self.sdn_app.traffic_service.generate_iperf(
                src_host=body["src_host"],
                dst_host=body["dst_host"],
                duration=body.get("duration", 10),
                udp=body.get("udp", False),
                bandwidth=body.get("bandwidth"),
                port=body.get("port", 5201),
                timeout=body.get("timeout", 20)
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/traffic/iperf: %s", e)
            return error_response(e, status=400)
    
    @route("disable_port", "/api/ports/disable", methods=["POST", "OPTIONS"])
    def disable_port(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "dpid", "port_no")

            result = self.sdn_app.topology_service.set_port_state(
                body["dpid"],
                body["port_no"],
                up=False
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/disable: %s", e)
            return error_response(e, status=400)

    @route("enable_port", "/api/ports/enable", methods=["POST", "OPTIONS"])
    def enable_port(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "dpid", "port_no")

            result = self.sdn_app.topology_service.set_port_state(
                body["dpid"],
                body["port_no"],
                up=True
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/ports/enable: %s", e)
            return error_response(e, status=400)
    
    @route("forget_link", "/api/links/forget", methods=["POST", "OPTIONS"])
    def forget_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            require_fields(body, "src", "dst")

            result = self.sdn_app.topology_service.forget_link(
                body["src"],
                body["dst"]
            )
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error en POST /api/links/forget: %s", e)
            return error_response(e, status=400)

    @route("attach_host_link", "/api/hosts/link/attach", methods=["POST", "OPTIONS"])
    def attach_host_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            result = self.sdn_app.attach_host_link(body)
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error conectando host-link: %s", e)
            return error_response(e, status=400)

    @route("detach_host_link", "/api/hosts/link/detach", methods=["POST", "OPTIONS"])
    def detach_host_link(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            body = read_json_body(req)
            result = self.sdn_app.detach_host_link(body)
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error desconectando host-link: %s", e)
            return error_response(e, status=400)

    @route("forget_host", "/api/hosts/forget/{mac}", methods=["DELETE", "OPTIONS"])
    def forget_host(self, req, **kwargs):
        if req.method == "OPTIONS":
            return cors_preflight()

        try:
            result = self.sdn_app.forget_host_by_mac(kwargs["mac"])
            return success_response(result)
        except Exception as e:
            self.sdn_app.logger.exception("Error olvidando host: %s", e)
            return error_response(e, status=400)
        
