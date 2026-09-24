import os
import shutil
import subprocess

from pathlib import Path

import pytest

from conftest import ROOT


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
