import os

from pathlib import Path
from typing import NamedTuple

import pytest

# `moon.util` binds its output sink at import time.
os.environ.setdefault('LUNA_MUTE', '1')

ROOT = Path(__file__).resolve().parent.parent

ZONE_FILE = '''\
[home]
host = gw1 box1
arc = ofgw:office

[office]
host = ofgw ofbox
# TEST-NET-3 (RFC 5737) matches no real interface, so this zone is never local.
subnet = 203.0.113.0/24
'''

# `Port=2222` and the tilde exercise the two ways a value survives rendering.
SSH_CONFIG = '''\
Host gw1
  Hostname 10.0.0.1
  User me

Host box1
  Hostname 10.0.0.2

Host ofgw
  Hostname 192.168.1.1
  Port=2222

Host ofbox
  Hostname 192.168.1.2
  IdentityFile ~/.ssh/id_office
'''


class Tree(NamedTuple):
    zone_file: Path
    input_file: Path


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    '''A topology where `home` is local and `office` is reached through `ofgw`.'''
    zone_file = tmp_path / 'zone.ini'
    zone_file.write_text(ZONE_FILE, encoding='utf-8')
    input_file = tmp_path / 'sshconfig'
    input_file.write_text(SSH_CONFIG, encoding='utf-8')
    return Tree(zone_file, input_file)
