from ipaddress import AddressValueError, IPv4Address, IPv4Network

import netifaces


# `netifaces.gateways()` is faster than checking all interfaces.
class Gateways:
    def __init__(self) -> None:
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

    def check_subnet(self, net: IPv4Network) -> bool:
        return any(gw in net for gw in self._gws)
