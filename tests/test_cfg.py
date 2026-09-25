from io import StringIO
from pathlib import Path

import pytest

from cfg import ZoneConfig, parse_arc
from moon.route import ZoneSet
from moon.syn import Config


# The forms of the zone.ini reference, with 'far' as a zone and 'gw' as a host.
@pytest.mark.parametrize(
    ('arc', 'parsed'),
    [
        ('gw:far:5', ('far', 'gw', 5)),
        ('gw:far', ('far', 'gw', 20)),
        ('far', ('far', '', 20)),
        ('far:5', ('far', '', 5)),
        ('gw', (None, 'gw', 20)),
        ('gw:5', (None, 'gw', 5)),
    ],
)
def test_parse_arc(arc: str, parsed: tuple[str | None, str, int]):
    assert parse_arc(arc, frozenset(('far',))) == parsed


@pytest.mark.parametrize('arc', ['gw:far:cheap', 'a:b:c:d'])
def test_parse_arc_rejects_a_malformed_arc(arc: str):
    with pytest.raises(ValueError, match='malformed arc'):
        parse_arc(arc, frozenset(('far',)))


# 'box-a' sorts between 'box' and its other aliases, and 'boxy' has an address of its own.
DISCOVERY_ZONE_FILE = '''\
[home]
host = gw1 box-a
arc = ofgw:office

[office]
host = ofgw
subnet = 203.0.113.0/24
'''

DISCOVERY_SSH_CONFIG = '''\
Host box
  Hostname 203.0.113.5
Host box-a
  Hostname 203.0.113.6
Host box-b
Host boxy
  Hostname 203.0.113.7
Host ofgw
  Hostname 203.0.113.1
Host ofgw2
  Hostname 203.0.113.2
Host other
  Hostname 192.0.2.9
'''


def discover(tmp_path: Path, zone_file: str) -> ZoneSet:
    (tmp_path / 'zone.ini').write_text(zone_file, encoding='utf-8')
    return ZoneConfig(str(tmp_path / 'zone.ini'), Config(StringIO(DISCOVERY_SSH_CONFIG))).route(
        None
    )


def test_hosts_in_a_subnet_join_its_zone_with_their_prefixed_names(tmp_path: Path):
    g = discover(tmp_path, DISCOVERY_ZONE_FILE)
    assert g.resolve('box') == ('box', 'ofgw')
    assert g.resolve('ofgw2') == ('ofgw2', 'ofgw')
    # A name written in zone.ini stays where it is written and never becomes an alias.
    assert set(g.aliases()) == {'box-b', 'boxy'}
    assert set(g.hosts()) == {'gw1', 'box-a', 'ofgw', 'box', 'ofgw2'}
    assert 'other' not in g


def test_strict_host_keeps_the_zone_as_written(tmp_path: Path):
    g = discover(
        tmp_path, DISCOVERY_ZONE_FILE.replace('[office]\n', '[office]\nstrict-host = true\n')
    )
    assert set(g.hosts()) == {'gw1', 'box-a', 'ofgw'}
    assert not set(g.aliases())
