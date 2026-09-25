import os
import shutil
import subprocess
import time

from pathlib import Path

import pytest

from conftest import ROOT, SSH_CONFIG, Tree


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
@pytest.mark.parametrize(('flags', 'name'), [((), 'sshconfig'), (('-i', 'custom'), 'custom')])
def test_direct_mode_copies_the_requested_input(tmp_path: Path, flags: tuple[str, ...], name: str):
    (tmp_path / name).write_text('Host h\n', encoding='utf-8')
    out = tmp_path / 'out.inc'
    argv = ('bash', str(ROOT / 'install.sh'), '-c', str(tmp_path), '-o', str(out), *flags)
    subprocess.run(
        argv,
        check=True,
        capture_output=True,
        timeout=30,
        # HOME is redirected so a misparsed '-o' cannot reach the real ssh config.
        env=os.environ | {'HOME': str(tmp_path), 'LUNA_SSH_DIRECT': '1', 'LUNA_MUTE': '1'},
    )
    assert out.read_text(encoding='utf-8') == 'Host h\n'


# A timezone condition makes luna record a state, which lets it skip regeneration.
LOCAL_ZONE_FILE = f'''\
[home]
host = gw1
timezone = {time.localtime().tm_gmtoff / 3600}
arc = ofgw:office

[office]
host = ofgw ofbox
subnet = 203.0.113.0/24
'''


def run_install(
    tmp_path: Path, env: dict[str, str], root: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    argv = ('bash', str(root / 'install.sh'), '-c', str(tmp_path), '-o', str(tmp_path / 'out.inc'))
    return subprocess.run(
        (*argv, 'ofbox'),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ | {'HOME': str(tmp_path)} | env,
    )


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_routed_run_after_a_direct_one_regenerates(tmp_path: Path):
    (tmp_path / 'zone.ini').write_text(LOCAL_ZONE_FILE, encoding='utf-8')
    (tmp_path / 'sshconfig').write_text(SSH_CONFIG, encoding='utf-8')
    out = tmp_path / 'out.inc'

    run_install(tmp_path, {'LUNA_MUTE': '1'})
    run_install(tmp_path, {'LUNA_MUTE': '1', 'LUNA_SSH_DIRECT': '1'})
    assert 'ProxyJump' not in out.read_text(encoding='utf-8')

    # Within the two-second window of the copy.
    run_install(tmp_path, {'LUNA_MUTE': '1'})
    assert 'ProxyJump ofgw' in out.read_text(encoding='utf-8')


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_changed_sources_regenerate(tmp_path: Path):
    root = tmp_path / 'luna'
    shutil.copytree(ROOT / 'moon', root / 'moon', ignore=shutil.ignore_patterns('__pycache__'))
    for f in (*ROOT.glob('*.py'), *ROOT.glob('*.sh')):
        shutil.copy(f, root)
    (tmp_path / 'zone.ini').write_text(LOCAL_ZONE_FILE, encoding='utf-8')
    (tmp_path / 'sshconfig').write_text(SSH_CONFIG, encoding='utf-8')
    out = tmp_path / 'out.inc'
    run_install(tmp_path, {'LUNA_MUTE': '1'}, root)

    # Past the two-second window, with the output newer than its inputs.
    now = time.time()
    aged = (tmp_path / 'zone.ini', tmp_path / 'sshconfig', *root.glob('**/*.py'))
    for f in aged:
        os.utime(f, (now - 20, now - 20))
    os.utime(out, (now - 10, now - 10))
    written = out.stat().st_mtime_ns
    run_install(tmp_path, {'LUNA_MUTE': '1'}, root)
    assert out.stat().st_mtime_ns == written

    os.utime(root / 'moon' / 'route.py')
    run_install(tmp_path, {'LUNA_MUTE': '1'}, root)
    assert out.stat().st_mtime_ns > written


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_scripts_are_quiet_outside_a_git_repository(tmp_path: Path):
    # The quick start puts the config in ~/.ssh, which is usually no repository.
    (tmp_path / 'zone.ini').write_text(LOCAL_ZONE_FILE, encoding='utf-8')
    (tmp_path / 'sshconfig').write_text(SSH_CONFIG, encoding='utf-8')
    env = {'GIT_CEILING_DIRECTORIES': str(tmp_path.parent)}
    assert 'fatal' not in run_install(tmp_path, env).stderr

    wrapper = subprocess.run(
        ('bash', str(ROOT / 'ssh.sh'), 'ofbox'),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ
        | env
        | {
            'LUNA_SSH': 'true',
            'LUNA_ENTRY': str(ROOT / 'luna.py'),
            'LUNA_ZONE': str(tmp_path / 'zone.ini'),
        },
    )
    assert 'fatal' not in wrapper.stderr


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
@pytest.mark.parametrize('verbose', [False, True])
def test_wrapper_prints_diagnostics_only_when_verbose(tree: Tree, verbose: bool):
    env = {k: v for k, v in os.environ.items() if k not in {'LUNA_MUTE', 'LUNA_VERBOSE'}}
    if verbose:
        env['LUNA_VERBOSE'] = '1'
    r = subprocess.run(
        ('bash', str(ROOT / 'ssh.sh'), 'ofbox'),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=env
        | {
            'LUNA_SSH': 'true',
            'LUNA_ENTRY': str(ROOT / 'luna.py'),
            'LUNA_ZONE': str(tree.zone_file),
        },
    )
    # The remote command's output owns stdout.
    assert not r.stdout
    err = r.stderr
    assert '[ofgw] -> {office: ofgw, ofbox} (20)' in err
    assert ('connecting to ofbox' in err) == verbose
    assert ("executing '-J ofgw ofbox'" in err) == verbose
