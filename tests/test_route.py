from moon.route import ZoneSet


def test_contains_finds_a_host_by_its_alias():
    g = ZoneSet()
    office = g.add([['ofgw', 'ofgw-pub']])
    home = g.add([['gw1']])
    assert g.contains(office, 'ofgw-pub')
    assert not g.contains(home, 'ofgw-pub')
