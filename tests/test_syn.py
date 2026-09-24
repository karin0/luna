from io import StringIO

import pytest

from moon.syn import Config, Directive


def opts(cfg: Config, host: str) -> list[str]:
    return [str(line) for line in cfg.query(host)]


# ssh_config(5): a directive is separated from its value by whitespace, or by
# whitespace and exactly one '='.
@pytest.mark.parametrize(
    ('line', 'opt', 'values'),
    [
        ('Port 2222', 'port', ('2222',)),
        ('Port=2222', 'port', ('2222',)),
        ('Port =2222', 'port', ('2222',)),
        ('Port= 2222', 'port', ('2222',)),
        ('Port = 2222', 'port', ('2222',)),
        ('Port  =  2222', 'port', ('2222',)),
        ('Hostname=1.2.3.4', 'hostname', ('1.2.3.4',)),
        ('Host=foo bar', 'host', ('foo', 'bar')),
        ('  IdentityFile ~/.ssh/id_ed25519', 'identityfile', ('~/.ssh/id_ed25519',)),
        ('Port 2222  # trailing', 'port', ('2222',)),
        # Only the separator is consumed; a value keeps its own '='.
        ('SetEnv FOO=bar', 'setenv', ('FOO=bar',)),
        # ssh hands a command to the shell as one string.
        ('ProxyCommand = nc %h %p', 'proxycommand', ('nc %h %p',)),
        ('Port="2222"', 'port', ('2222',)),
        ('# Port=2222', '', ()),
        ('', '', ()),
    ],
)
def test_directive_separators(line: str, opt: str, values: tuple[str, ...]):
    d = Directive(line)
    assert d.opt == opt
    assert d.values == values


def test_hostname_survives_a_spaced_separator():
    # Zone discovery matches these addresses against the configured subnets.
    cfg = Config(StringIO('Host a\n  Hostname = 1.2.3.4\n'))
    assert tuple(cfg.hostnames()) == (('a', '1.2.3.4'),)


def test_rendered_directive_carries_its_value():
    # ssh rejects the whole file when a keyword arrives with no argument.
    assert str(Directive('Port=2222')) == 'Port 2222'


@pytest.mark.parametrize(
    'line',
    [
        'ProxyCommand nc %h %p 2>/dev/null',
        'ProxyCommand ssh -W %h:%p jump | cat',
        'LocalCommand echo $HOME; date',
        "LocalCommand echo don't",
    ],
)
def test_rendered_command_keeps_its_shell_syntax(line: str):
    assert str(Directive(line)) == line


# ssh_config(5) PATTERNS: '?' matches exactly one character.
@pytest.mark.parametrize(
    ('host', 'hit'),
    [('web1', True), ('webx', True), ('web', False), ('web12', False)],
)
def test_single_character_wildcard(host: str, hit: bool):
    cfg = Config(StringIO('Host web?\n  Port 2022\n'))
    assert (opts(cfg, host) == ['Port 2022']) is hit


def test_patterns_are_not_host_names():
    # `Config.hosts()` feeds zone discovery, which needs names it can connect to.
    cfg = Config(StringIO('Host web? real\n  Port 2022\n'))
    assert tuple(cfg.hosts()) == ('real',)


def test_a_block_is_registered_once_however_many_patterns_it_carries():
    cfg = Config(StringIO('Host *.a *.b *.c\n  Port 22\n'))
    # `query` merges repeated blocks, so only the registry shows a duplicate.
    wildcards = cfg._wildcards  # pyright: ignore[reportPrivateUsage]
    assert len(wildcards) == len(set(wildcards))


def test_negated_pattern_excludes_a_host():
    cfg = Config(StringIO('Host * !secret\n  Port 22\n'))
    assert opts(cfg, 'other') == ['Port 22']
    assert opts(cfg, 'secret') == []


def test_attached_alias_connects_to_a_host_without_hostname():
    # ssh would resolve the alias itself, so it has to name its source host.
    cfg = Config(StringIO('Host a\n  Port 2022\n'))
    cfg.attach('d.a', 'a')
    assert opts(cfg, 'd.a') == ['Port 2022', 'Hostname a']


def test_attached_alias_keeps_the_hostname_of_its_source():
    cfg = Config(StringIO('Host a\n  Hostname 192.0.2.1\n'))
    cfg.attach('d.a', 'a')
    assert opts(cfg, 'd.a') == ['Hostname 192.0.2.1']
