import argparse

import pytest

from luna import find_host, rewrite


# ssh(1) argument shapes the wrapper has to see through to find the destination.
@pytest.mark.parametrize(
    ('argv', 'found'),
    [
        (['host'], (0, 'host')),
        (['-v', 'host'], (1, 'host')),
        (['-4v', 'host'], (1, 'host')),
        (['-p', '2222', 'host'], (2, 'host')),
        (['-p2222', 'host'], (1, 'host')),
        (['--', '-dashed'], (1, '-dashed')),
        (['-v'], None),
        ([], None),
    ],
)
def test_find_host(argv, found):
    assert find_host(argv) == found


@pytest.mark.parametrize(
    ('dest', 'rewritten'),
    [
        ('ofbox', ('-J', 'ofgw', 'ofbox')),
        # The login name belongs to the destination, not to the jump host.
        ('admin@ofbox', ('-J', 'ofgw', 'admin@ofbox')),
        ('ofgw', ('ofgw',)),
        ('box1', ('box1',)),
        ('d.ofbox', ('ofbox',)),
        ('unmanaged.example.com', ('unmanaged.example.com',)),
    ],
)
def test_rewrite(tree, dest, rewritten):
    args = argparse.Namespace(
        input_file=str(tree.input_file), zone_file=str(tree.zone_file), host=None
    )
    assert tuple(rewrite([dest, 'uptime'], args)) == (*rewritten, 'uptime')
