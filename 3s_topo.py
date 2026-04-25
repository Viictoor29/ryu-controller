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


class s3Topo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        s5 = self.addSwitch('s5')
        s3 = self.addSwitch('s3')

        h169 = self.addHost(
            'h169',
            ip='10.0.0.1/24',
            mac=mac_from_host_name('h169')
        )

        h69 = self.addHost(
            'h69',
            ip='10.0.0.69/24',
            mac=mac_from_host_name('h69')
        )

        h170 = self.addHost(
            'h170',
            ip='10.0.0.170/24',
            mac=mac_from_host_name('h170')
        )

        self.addLink(h169, s1)
        self.addLink(h69, s5)
        self.addLink(h170, s3)

        #self.addLink(s1, s5)
        self.addLink(s1, s3)
        self.addLink(s5, s3)


topos = {'s3Topo': lambda: s3Topo()}