import json
import urllib.parse
import urllib.request


class RyuClientMixin:
    """Cliente HTTP mínimo para notificar cambios al controlador Ryu."""

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

        host = None
        for node in (link.intf1.node, link.intf2.node):
            if node in self.net.hosts:
                host = node
                break

        if host is not None:
            mac = self.safe_host_mac(host) or self.mac_from_host_name(host.name)
            if mac:
                try:
                    results.append({
                        "kind": "host-link",
                        "host": host.name,
                        "mac": mac,
                        "result": self.notify_ryu_forget_host(mac),
                    })
                except Exception as e:
                    print(f"[mininet-api] Error avisando a Ryu para olvidar host: {e}")
                    results.append({"kind": "host-link", "host": host.name, "mac": mac, "error": str(e)})

        return results

    def notify_ryu_forget_link(self, src, dst):
        payload = json.dumps({"src": src, "dst": dst}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ryu_api_url}/api/links/forget",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Ryu respondió {resp.status}: {body}")
            return body

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
