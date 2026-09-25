import os
import subprocess
import sys

import pytest

from conftest import ROOT, Tree

from luna import Args, find_host, rewrite


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
def test_find_host(argv: list[str], found: tuple[int, str] | None):
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
def test_rewrite(tree: Tree, dest: str, rewritten: tuple[str, ...]):
    args = Args(input_file=str(tree.input_file), zone_file=str(tree.zone_file))
    assert tuple(rewrite([dest, 'uptime'], args)) == (*rewritten, 'uptime')


@pytest.mark.parametrize(
    'argv',
    [
        ['-J', 'other', 'ofbox'],
        ['-vJother', 'ofbox'],
        ['-o', 'ProxyJump=other', 'ofbox'],
        ['-oProxyCommand nc %h %p', 'ofbox'],
        ['-o', 'proxyjump none', 'ofbox'],
        ['ofbox', '-J', 'other'],
        ['ofbox', '-o', 'ProxyJump=other', 'uptime'],
    ],
)
def test_rewrite_keeps_a_jump_given_on_the_command_line(tree: Tree, argv: list[str]):
    # ssh rejects a second -J, and the first ProxyJump would override the user's.
    args = Args(input_file=str(tree.input_file), zone_file=str(tree.zone_file))
    assert tuple(rewrite(list(argv), args)) == tuple(argv)


def test_rewrite_routes_past_other_options(tree: Tree):
    args = Args(input_file=str(tree.input_file), zone_file=str(tree.zone_file))
    assert tuple(rewrite(['-o', 'User=me', 'ofbox'], args)) == (
        '-J',
        'ofgw',
        '-o',
        'User=me',
        'ofbox',
    )


def test_rewrite_leaves_the_command_unparsed(tree: Tree):
    args = Args(input_file=str(tree.input_file), zone_file=str(tree.zone_file))
    argv = ['ofbox', 'grep', '-J', 'x']
    assert tuple(rewrite(list(argv), args)) == ('-J', 'ofgw', *argv)


def test_print_cmd_routes_without_an_input_file(tree: Tree):
    # The input file only feeds host discovery, so leaving it out still routes.
    argv = (sys.executable, str(ROOT / 'luna.py'), '-p', '-z', str(tree.zone_file), '--', 'ofbox')
    out = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        cwd=tree.zone_file.parent,
        env=os.environ | {'LUNA_MUTE': '1'},
    ).stdout
    assert out == 'ssh -J ofgw ofbox\n'
