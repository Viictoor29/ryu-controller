import threading

from .http_server import HttpServerMixin
from .state_service import StateServiceMixin
from .node_service import NodeServiceMixin
from .link_service import LinkServiceMixin
from .topology_apply_service import TopologyApplyServiceMixin
from .normalizers import NormalizersMixin
from .ryu_client import RyuClientMixin
from .mininet_helpers import MininetHelpersMixin


class MininetAPIService(
    HttpServerMixin,
    StateServiceMixin,
    NodeServiceMixin,
    LinkServiceMixin,
    TopologyApplyServiceMixin,
    NormalizersMixin,
    RyuClientMixin,
    MininetHelpersMixin,
):
    """API REST mínima para modificar una red Mininet viva.

Importante:
- Este servicio NO es una API aparte que cree otro Mininet.
- Debe ejecutarse dentro del mismo proceso que creó el objeto `net`.
- El runner `mininet_runner_api.py` ya lo hace al instanciar MininetAPIService(net, ...).

Endpoints principales:
- GET  /api/mininet/status
- GET  /api/mininet/topology/export
- POST /api/mininet/topology/apply
- POST /api/mininet/topology/clear
- POST /api/mininet/hosts
- POST /api/mininet/switches
- POST /api/mininet/links
- POST /api/mininet/links/add
- POST /api/mininet/links/delete
- DELETE /api/mininet/hosts/{name}
- DELETE /api/mininet/switches/{name}
- DELETE /api/mininet/links
- POST /api/mininet/pingall"""

    def __init__(self, net, host="127.0.0.1", port=8081, ryu_api_url="http://127.0.0.1:8080"):
        self.net = net
        self.host = host
        self.port = int(port)
        self.server = None
        self.thread = None
        self.lock = threading.RLock()
        self.ryu_api_url = ryu_api_url.rstrip("/")
        self.last_applied_scenario = None
