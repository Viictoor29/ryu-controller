from mininet.topo import Topo
import re


def mac_from_host_name(name):
    m = re.search(r'\d+$', name)
    if not m:
        raise ValueError(f"El host {name} no termina en número")

    n = int(m.group())
    if n < 1 or n > 255:
        raise ValueError("El número del host debe estar entre 1 y 255")

    return f"00:00:00:00:00:{n:02x}"


class SimpleTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s5')

        hx_name = 'h169'
        hy_name = 'h69'

        hx = self.addHost(
            hx_name,
            ip='10.0.0.1/24',
            mac=mac_from_host_name(hx_name)
        )

        hy = self.addHost(
            hy_name,
            ip='10.0.0.69/24',
            mac=mac_from_host_name(hy_name)
        )

        self.addLink(hx, s1)
        self.addLink(s1, s2)
        self.addLink(s2, hy)


topos = {'simpletopo': lambda: SimpleTopo()}