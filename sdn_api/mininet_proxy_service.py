# mininet_proxy_service.py
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class MininetProxyService:
    def __init__(self, app, base_url="http://127.0.0.1:5001"):
        self.app = app
        self.base_url = base_url.rstrip("/")

    def _request(self, method, path, data=None, timeout=10):
        url = f"{self.base_url}{path}"
        payload = None
        headers = {"Content-Type": "application/json"}

        if data is not None:
            payload = json.dumps(data).encode("utf-8")

        req = Request(url, data=payload, headers=headers, method=method)

        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as e:
            try:
                body = e.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
            except Exception:
                parsed = {"ok": False, "error": str(e)}
            raise RuntimeError(parsed.get("error", str(e)))
        except URLError as e:
            raise RuntimeError(f"No se pudo conectar con la API interna de Mininet: {e}")
        except Exception as e:
            raise RuntimeError(str(e))

    def create_host(self, name, ip=None, mac=None):
        payload = {"name": name}
        if ip is not None:
            payload["ip"] = ip
        if mac is not None:
            payload["mac"] = mac
        return self._request("POST", "/hosts", payload)

    def delete_host(self, name):
        return self._request("DELETE", "/hosts", {"name": name})

    def create_switch(self, name, protocols="OpenFlow13"):
        return self._request("POST", "/switches", {
            "name": name,
            "protocols": protocols
        })

    def delete_switch(self, name):
        return self._request("DELETE", "/switches", {"name": name})

    def create_link(self, node1, node2, params=None):
        return self._request("POST", "/links", {
            "node1": node1,
            "node2": node2,
            "params": params or {}
        })

    def delete_link(self, node1, node2, all_links=False):
        return self._request("DELETE", "/links", {
            "node1": node1,
            "node2": node2,
            "all_links": all_links
        })