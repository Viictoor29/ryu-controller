#!/usr/bin/env python3

import argparse
import importlib
import time

import sys

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel


def load_topology(module_name, class_name):
    """
    Carga dinámicamente una clase de topología desde un módulo Python.
    Ejemplo:
        module_name = "simple_topo"
        class_name = "SimpleTopo"
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(
            f"No se pudo importar el módulo '{module_name}': {e}"
        )

    try:
        topo_class = getattr(module, class_name)
    except AttributeError:
        raise AttributeError(
            f"El módulo '{module_name}' no tiene la clase '{class_name}'"
        )

    return topo_class()


def run():
    parser = argparse.ArgumentParser(
        description="Runner genérico de Mininet para cualquier topología Python"
    )
    parser.add_argument(
        "--module",
        required=True,
        help="Nombre del módulo Python donde está la topología, ej: simple_topo"
    )
    parser.add_argument(
        "--topo",
        required=True,
        help="Nombre de la clase Topo, ej: SimpleTopo"
    )
    parser.add_argument(
        "--controller-ip",
        default="127.0.0.1",
        help="IP del controlador remoto Ryu (por defecto 127.0.0.1)"
    )
    parser.add_argument(
        "--controller-port",
        type=int,
        default=6653,
        help="Puerto del controlador remoto Ryu (por defecto 6653)"
    )
    parser.add_argument(
        "--switch",
        default="ovsk",
        choices=["ovsk"],
        help="Tipo de switch (por ahora solo ovsk)"
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="No ejecutar 'mn -c' antes de arrancar"
    )
    parser.add_argument(
        "--skip-pingall",
        action="store_true",
        help="No ejecutar pingAll() al arrancar"
    )

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

    try:
        net.start()

        if not args.skip_pingall:
            print("\n*** Ejecutando pingAll para descubrir hosts/IPs...\n")

            #net.pingAll()

        print("\n*** Red arrancada. Entrando en CLI de Mininet...\n")
        CLI(net)

    finally:
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()