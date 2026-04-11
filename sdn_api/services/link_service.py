from utils.validators import normalize_endpoint


class LinkService:
    def __init__(self, app, topology_service, tc_service):
        self.app = app
        self.topology_service = topology_service
        self.tc_service = tc_service

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

        return {
            "dpid": str(dpid),
            "port_no": port_no,
            "state": "up" if up else "down"
        }

    def disable_link(self, src, dst):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=False)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=False)

        self.topology_service.set_link_inventory_state(src, dst, enabled=False)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "disabled"
        }

    def enable_link(self, src, dst):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        result_src = self.set_port_state(src["dpid"], src["port_no"], up=True)
        result_dst = self.set_port_state(dst["dpid"], dst["port_no"], up=True)

        self.topology_service.set_link_inventory_state(src, dst, enabled=True)

        return {
            "src": result_src,
            "dst": result_dst,
            "link_state": "enabled"
        }

    def set_link_loss(self, src, dst, loss):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        current_delay, current_bw = self.tc_service.set_link_loss(src, dst)
        result = self.tc_service.update_link_tc(src, dst, delay=current_delay, loss=loss, bandwidth=current_bw)
        result["link_state"] = "loss_updated"
        return result

    def set_link_delay(self, src, dst, delay):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        current_loss, current_bw = self.tc_service.set_link_delay(src, dst)
        result = self.tc_service.update_link_tc(src, dst, delay=delay, loss=current_loss, bandwidth=current_bw)
        result["link_state"] = "delay_updated"
        return result

    def set_link_bandwidth(self, src, dst, bandwidth):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        current_delay, current_loss = self.tc_service.set_link_bandwidth(src, dst)
        result = self.tc_service.update_link_tc(src, dst, delay=current_delay, loss=current_loss, bandwidth=bandwidth)
        result["link_state"] = "bandwidth_updated"
        return result

    def clear_link_tc(self, src, dst):
        src = normalize_endpoint(src, "src")
        dst = normalize_endpoint(dst, "dst")

        return self.tc_service.clear_link_tc(src, dst)