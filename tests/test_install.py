import os
import shutil
import subprocess
import time

from pathlib import Path

import pytest

from conftest import ROOT, SSH_CONFIG


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


def run_install(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    argv = ('bash', str(ROOT / 'install.sh'), '-c', str(tmp_path), '-o', str(tmp_path / 'out.inc'))
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
