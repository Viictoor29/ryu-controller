#!/usr/bin/env python3

import argparse
import importlib

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel

from mininet_live_api import MininetAPIService


def load_topology(module_name, class_name):
    """
    Carga una topología por nombre de módulo y clase.

    Compatibilidad:
    - Nuevo formato recomendado: --module topologies.simple_topo
    - Formato antiguo:          --module simple_topo
      Si falla el import directo, se intenta topologies.<module_name>.
    """
    tried_modules = []

    candidates = [module_name]
    if "." not in module_name:
        candidates.append(f"topologies.{module_name}")

    last_error = None
    for candidate in candidates:
        tried_modules.append(candidate)
        try:
            module = importlib.import_module(candidate)
            break
        except ImportError as e:
            last_error = e
    else:
        raise ImportError(
            f"No se pudo importar el módulo de topología. Intentados: {', '.join(tried_modules)}. "
            f"Último error: {last_error}"
        )

    try:
        topo_class = getattr(module, class_name)
    except AttributeError:
        raise AttributeError(
            f"El módulo '{module.__name__}' no tiene la clase '{class_name}'"
        )

    return topo_class()


def run():
    parser = argparse.ArgumentParser(description="Runner genérico de Mininet con API REST dinámica")
    parser.add_argument("--module", required=True)
    parser.add_argument("--topo", required=True)
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--switch", default="ovsk", choices=["ovsk"])
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--skip-pingall", action="store_true")
    parser.add_argument("--api-host", default="0.0.0.0")
    parser.add_argument("--api-port", type=int, default=8081)
    parser.add_argument("--disable-api", action="store_true")
    parser.add_argument("--ryu-api-url", default="http://127.0.0.1:8080")

    args = parser.parse_args()
    topo = load_topology(args.module, args.topo)

    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name,
            ip=args.controller_ip,
            port=args.controller_port
        ),
        switch=OVSSwitch,
        autoSetMacs=True
    )

    api = None

    try:
        net.start()

        if not args.disable_api:
            api = MininetAPIService(
                net,
                host=args.api_host,
                port=args.api_port,
                ryu_api_url=args.ryu_api_url,
            )
            api.start()

        if not args.skip_pingall:
            #print("\n*** Ejecutando pingAll para descubrir hosts/IPs...\n")
            #net.pingAll()
            next

        print("\n*** Red arrancada. Entrando en CLI de Mininet...\n")
        CLI(net)

    finally:
        if api:
            api.stop()
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
