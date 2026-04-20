from mininet.topo import Topo


class SimpleTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')

        h1 = self.addHost('h2', ip='10.0.0.1/24')
        h2 = self.addHost('h1', ip='10.0.0.69/24')

        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s2, h2)


topos = {'simpletopo': lambda: SimpleTopo()}
