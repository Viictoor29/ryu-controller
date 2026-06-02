import json
import urllib.parse
import urllib.request


class RyuClientMixin:
    """Cliente HTTP mínimo para notificar cambios al controlador Ryu."""

    def host_payload_from_node(self, host):
        ip = self.safe_host_ip(host)
        mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)

        payload = {
            "name": host.name,
            "mac": mac,
        }

        if ip:
            payload["ip"] = ip
            payload["ipv4"] = [ip]

        return payload

    def switch_endpoint_from_link(self, link):
        for intf in (link.intf1, link.intf2):
            endpoint = self.endpoint_from_intf(intf)
            if endpoint:
                return endpoint
        return None

    def host_from_link(self, link):
        for node in (link.intf1.node, link.intf2.node):
            if node in self.net.hosts:
                return node
        return None

    def post_ryu_json(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ryu_api_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {body}")
            return body

    def get_ryu_json(self, path, timeout=2):
        req = urllib.request.Request(f"{self.ryu_api_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {raw}")
            return json.loads(raw) if raw else {}

    def get_ryu_blocked_ips(self):
        try:
            body = self.get_ryu_json("/api/traffic/blocked-ips", timeout=2)
            data = body.get("data", body) if isinstance(body, dict) else {}
            return list(data.get("blocked_ips", []) or [])
        except Exception as e:
            print(f"[mininet-api] No se pudieron leer IPs bloqueadas desde Ryu: {e}")
            return []

    def notify_ryu_before_link_delete(self, link):
        results = []
        ep1 = self.endpoint_from_intf(link.intf1)
        ep2 = self.endpoint_from_intf(link.intf2)

        if ep1 and ep2:
            try:
                results.append({
                    "kind": "switch-link",
                    "src": ep1,
                    "dst": ep2,
                    "result": self.notify_ryu_forget_link(ep1, ep2),
                })
            except Exception as e:
                print(f"[mininet-api] Error avisando a Ryu para borrar link: {e}")
                results.append({"kind": "switch-link", "src": ep1, "dst": ep2, "error": str(e)})
            return results

        host = self.host_from_link(link)
        switch_ep = self.switch_endpoint_from_link(link)

        if host is not None:
            try:
                host_payload = self.host_payload_from_node(host)
                results.append({
                    "kind": "host-link",
                    "host": host.name,
                    "mac": host_payload.get("mac"),
                    "switch": switch_ep,
                    "result": self.notify_ryu_detach_host_link(host_payload, switch_ep),
                })
            except Exception as e:
                print(f"[mininet-api] Error avisando a Ryu para desconectar host-link: {e}")
                results.append({
                    "kind": "host-link",
                    "host": getattr(host, "name", None),
                    "switch": switch_ep,
                    "error": str(e),
                })

        return results

    def notify_ryu_host_link_attached(self, host, switch_ep):
        host_payload = self.host_payload_from_node(host)
        return self.notify_ryu_attach_host_link(host_payload, switch_ep)

    def notify_ryu_attach_host_link(self, host_payload, switch_ep):
        if not host_payload.get("mac"):
            raise RuntimeError("No tengo MAC del host, no puedo avisar a Ryu")
        return self.post_ryu_json(
            "/api/hosts/link/attach",
            {"host": host_payload, "switch": switch_ep or {}},
        )

    def notify_ryu_detach_host_link(self, host_payload, switch_ep):
        if not host_payload.get("mac"):
            raise RuntimeError("No tengo MAC del host, no puedo avisar a Ryu")
        return self.post_ryu_json(
            "/api/hosts/link/detach",
            {"host": host_payload, "switch": switch_ep or {}},
        )

    def notify_ryu_forget_link(self, src, dst):
        return self.post_ryu_json("/api/links/forget", {"src": src, "dst": dst})

    def notify_ryu_forget_host(self, mac):
        if not mac:
            raise RuntimeError("No tengo MAC del host, no puedo avisar a Ryu")

        safe_mac = urllib.parse.quote(str(mac).lower(), safe="")
        url = f"{self.ryu_api_url}/api/hosts/forget/{safe_mac}"
        req = urllib.request.Request(url, method="DELETE")

        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {body}")
            return body
