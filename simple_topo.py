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

        h1_name = 'h2'
        h2_name = 'h13'

        h1 = self.addHost(
            h1_name,
            ip='10.0.0.1/24',
            mac=mac_from_host_name(h1_name)
        )

        h2 = self.addHost(
            h2_name,
            ip='10.0.0.69/24',
            mac=mac_from_host_name(h2_name)
        )

        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s2, h2)


topos = {'simpletopo': lambda: SimpleTopo()}