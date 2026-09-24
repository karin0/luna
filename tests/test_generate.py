import os
import shutil
import subprocess
import sys

from io import StringIO

import pytest

from conftest import ROOT

from moon.syn import Config


def generate(tree, host: str) -> Config:
    argv = (
        sys.executable,
        str(ROOT / 'luna.py'),
        '-z',
        str(tree.zone_file),
        '-i',
        str(tree.input_file),
        '-o',
        '-',
        host,
    )
    out = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=os.environ | {'LUNA_MUTE': '1'},
    ).stdout
    return Config(StringIO(out))


def opts(cfg: Config, host: str) -> list[str]:
    return [str(line) for line in cfg.query(host)]


def test_remote_zone_is_reached_through_its_gateway(tree):
    assert 'ProxyJump ofgw' in opts(generate(tree, 'ofbox'), 'ofbox')


def test_local_zone_needs_no_jump(tree):
    assert 'proxyjump' not in {line.dir.opt for line in generate(tree, 'box1').query('box1')}


def test_direct_alias_inherits_the_connection_options(tree):
    # 'd.<host>' exists to bypass the jump chain, so it needs the whole set.
    assert opts(generate(tree, 'ofbox'), 'd.ofgw') == [
        'Hostname 192.168.1.1',
        'Port 2222',
    ]


@pytest.mark.skipif(shutil.which('ssh') is None, reason='needs ssh(1)')
def test_generated_config_is_accepted_by_ssh(tree, tmp_path):
    out = tmp_path / 'config.inc'
    argv = (
        sys.executable,
        str(ROOT / 'luna.py'),
        '-z',
        str(tree.zone_file),
        '-i',
        str(tree.input_file),
        '-o',
        str(out),
        '-ff',
        'ofbox',
    )
    subprocess.run(
        argv, check=True, capture_output=True, timeout=30, env=os.environ | {'LUNA_MUTE': '1'}
    )
    # ssh exits 255 and abandons the file when a keyword arrives with no argument.
    subprocess.run(
        ('ssh', '-G', '-F', str(out), 'ofbox'), check=True, capture_output=True, timeout=30
    )


def test_generator_requires_an_input_file(tree):
    argv = (sys.executable, str(ROOT / 'luna.py'), '-z', str(tree.zone_file), '-o', '-')
    r = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ | {'LUNA_MUTE': '1'},
    )
    assert r.returncode == 2
    assert '-i/--input-file' in r.stderr


HEADER = '# Generated for the test'


def generate_files(tree, tmp_path, force: str):
    out = tmp_path / 'config.inc'
    argv = (
        sys.executable,
        str(ROOT / 'luna.py'),
        '-z',
        str(tree.zone_file),
        '-i',
        str(tree.input_file),
        '-o',
        str(out),
        '-H',
        HEADER,
        force,
        'ofbox',
    )
    subprocess.run(
        argv, check=True, capture_output=True, timeout=30, env=os.environ | {'LUNA_MUTE': '1'}
    )
    return out, out.with_name(out.name + '.flat')


# '-f' goes through the lock and '-ff' skips it; both write the flat config.
@pytest.mark.parametrize('force', ['-f', '-ff'])
def test_flat_config_lists_the_input_hosts_with_their_routes(tree, tmp_path, force):
    _, flat = generate_files(tree, tmp_path, force)
    text = flat.read_text(encoding='utf-8')
    cfg = Config(StringIO(text))

    # VS Code Remote - SSH breaks on inline comments; full-line ones are fine.
    assert all(line.startswith('#') for line in text.splitlines() if '#' in line)
    assert HEADER in text
    # The generated 'd.' hosts stay out of the client's host list.
    assert sorted(cfg.hosts()) == ['box1', 'gw1', 'ofbox', 'ofgw']
    assert 'ProxyJump ofgw' in opts(cfg, 'ofbox')


@pytest.mark.skipif(shutil.which('ssh') is None, reason='needs ssh(1)')
def test_flat_config_is_accepted_by_ssh(tree, tmp_path):
    _, flat = generate_files(tree, tmp_path, '-f')
    out = subprocess.run(
        ('ssh', '-G', '-F', str(flat), 'ofbox'),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert 'proxyjump ofgw' in out.splitlines()
