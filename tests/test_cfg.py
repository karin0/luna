import pytest

from cfg import parse_arc


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
