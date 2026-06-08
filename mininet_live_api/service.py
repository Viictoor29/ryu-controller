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

    def __init__(self, net, host="127.0.0.1", port=8081, ryu_api_url="http://127.0.0.1:8080"):
        self.net = net
        self.host = host
        self.port = int(port)
        self.server = None
        self.thread = None
        self.lock = threading.RLock()
        self.ryu_api_url = ryu_api_url.rstrip("/")
        self.last_applied_scenario = None
