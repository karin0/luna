import os
from ipaddress import AddressValueError, IPv4Address, IPv4Interface, IPv4Network

try:
    import netifaces
except ImportError:
    netifaces = None

from .util import dbg


def interfaces():
    if not netifaces or os.name == 'nt':
        # Calling `netifaces.ifaddresses()` for every interface seems slower than
        # `ipconfig` on Windows.
        import subprocess
        import re

        if os.name == 'nt':
            dbg("interfaces: netifaces not found on 'nt', falling back to 'ipconfig'")
            out = subprocess.check_output(('ipconfig'), timeout=2, text=True)
            reg = r'IPv4.+?[ \.]+?: (\d+\.\d+\.\d+\.\d+)\s*?.+?[ \.]+: (\d+\.\d+\.\d+\.\d+)'
            for m in re.finditer(reg, out):
                yield IPv4Interface((m[1], m[2]))
        elif os.name == 'posix':
            dbg("interfaces: netifaces not found on 'posix', falling back to 'ip addr'")
            out = subprocess.check_output(('ip', 'addr'), timeout=2, text=True)
            for m in re.finditer(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', out):
                yield IPv4Interface(m[1])
        else:
            dbg('interfaces: netifaces not found on unknown platform:', os.name)

        return

    for iface in netifaces.interfaces():
        for addr in netifaces.ifaddresses(iface).get(netifaces.AF_INET, ()):
            yield IPv4Interface((addr['addr'], addr['netmask']))


class Interfaces:
    def __init__(self) -> None:
        self.ints = {
            intf.network: intf for intf in interfaces() if not intf.ip.is_loopback
        }

    def __str__(self) -> str:
        return 'interfaces: ' + ', '.join(sorted(map(str, self.ints.values())))

    def check_subnet(
        self, net: IPv4Network, *, as_sub: bool = False, as_super: bool = False
    ) -> IPv4Interface | None:
        try:
            return self.ints[net]
        except KeyError:
            pass
        if as_sub or as_super:
            for intf_net, intf in self.ints.items():
                if (as_sub and net.subnet_of(intf_net)) or (
                    as_super and intf_net.subnet_of(net)
                ):
                    return intf


if netifaces:
    # `netifaces.gateways()` is faster than checking all interfaces.

    class Gateways:
        def __init__(self):
            self._gws: set[IPv4Address] = set()
            for gw in netifaces.gateways().values():
                for t in gw.values() if isinstance(gw, dict) else gw:
                    try:
                        ip = IPv4Address(t[0])
                    except AddressValueError:
                        pass
                    else:
                        if not ip.is_loopback:
                            self._gws.add(ip)

        def __str__(self) -> str:
            return 'gateways: ' + ', '.join(sorted(map(str, self._gws)))

        def check_subnet(self, net: IPv4Network) -> IPv4Address | None:
            for gw in self._gws:
                if gw in net:
                    return gw
