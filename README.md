# luna

luna chooses SSH jump hosts based on where your machine is.

Say you have a server `ofbox` in the office. At the office you connect to it directly. At home it is
only reachable through the office gateway `ofgw`, so you type `ssh -J ofgw ofbox`, or keep two
`Host` entries and remember which one to use. With luna you describe the networks once in
`zone.ini`, and `ssh ofbox` takes the right path wherever you are. Before each connection luna
reads the local timezone and network interfaces to find out which networks the machine is in,
computes the shortest path to the destination, and turns it into a `ProxyJump` chain.

## Requirements

- OpenSSH and Bash. On Windows, Git for Windows provides both (see the notes in [config](config)).
- Python 3.14 or newer, run as the `python3` (or `python`) found on `PATH`. The scripts leave any
  active virtualenv before starting it.
- Optionally `rich` for colored diagnostics, and `netifaces-plus` for faster network detection.
  Install them into that same interpreter. They are also declared as the `rich` and `netifaces`
  extras.

## Quick start

### 1. Get luna

```sh
git clone https://github.com/karin0/luna.git ~/.ssh/luna
```

### 2. Describe your networks

Write `~/.ssh/zone.ini`. Each section is a zone, a group of hosts that can reach each other
directly.

```ini
[home]
host = gw1 box1
arc = ofgw:office

[office]
host = ofgw ofbox
subnet = 192.168.1.0/24
```

The `home` zone has no condition, so luna always treats the machine as being in it. The `office`
zone applies when a local interface is on `192.168.1.0/24`. `arc = ofgw:office` says that from
`home`, the `office` zone is reached by jumping through `ofgw`. At home `ssh ofbox` becomes a jump
through `ofgw`, and at the office both zones apply, so it connects directly.

The names in `host` are the `Host` names from your SSH config. The full syntax is in
[zone.ini reference](#zoneini-reference).

### 3. Choose a mode

Generator mode keeps an include file for `~/.ssh/config` up to date, so every program that reads
the SSH config (`git`, `rsync`, `scp`, editors with remote extensions) takes the routes without
further setup. It reads only the `Host` blocks of your config, so choose it when your config is
made of `Host` blocks.

Wrapper mode puts a script named `ssh` in front of the real one and rewrites its command line. It
leaves the config files alone, so it suits configs that depend on `Match` or `Include`. Programs
only benefit when they find the wrapper on `PATH`.

### 4a. Set up generator mode

```sh
mv ~/.ssh/config ~/.ssh/sshconfig
cp ~/.ssh/luna/config ~/.ssh/config
```

Your own config now lives in `~/.ssh/sshconfig`, and that is the file you edit from here on.
`~/.ssh/config` holds only the two lines copied from [config](config). Before each connection its
`Match exec` line runs [install.sh](install.sh), which regenerates `~/.ssh/config.inc`, and the
`Include` line loads that file. The generated file is a copy of `sshconfig` with the jump options
added in front, and it carries a `DO NOT EDIT` header.

### 4b. Set up wrapper mode

Put [ssh.sh](ssh.sh) on `PATH` under the name `ssh`, ahead of the real one, and set the variables
below. Use exact paths, since the wrapper runs `LUNA_SSH` itself.

```sh
ln -s ~/.ssh/luna/ssh.sh ~/.local/bin/ssh
export LUNA_SSH=/usr/bin/ssh
```

| Variable | Default | Meaning |
|---|---|---|
| `LUNA_SSH` | `ssh` | The real `ssh` executable. |
| `LUNA_ENTRY` | `~/.ssh/luna/luna.py` | This repository's `luna.py`. |
| `LUNA_ZONE` | `~/.ssh/zone.ini` | The zone file. |
| `LUNA_CONFIG` | empty | An SSH config, read only to find hosts by subnet (see `strict-host`). |

### 5. Check the result

luna prints the routes it chose on standard error when you connect.

```
# [] -> {home: gw1, box1} (0)
# [ofgw] -> {office: ofgw, ofbox} (20)
```

Each line is a zone, the jumps that lead to it, and its total cost. In generator mode `ssh -G`
shows the options a connection would use, which runs luna as well.

```sh
ssh -G ofbox | grep -i proxyjump
```

In wrapper mode the following command prints the rewritten command, `ssh -J ofgw ofbox`, without
running it.

```sh
~/.ssh/luna/luna.py -p -z ~/.ssh/zone.ini -- ofbox
```

## VS Code Remote - SSH

Every regeneration also writes `~/.ssh/config.inc.flat`, a flat config with one `Host` block per
host of `sshconfig`, holding the options that apply to it and its route. It has no inline comments
and no `d.` hosts, so Remote - SSH can read it. Point the `remote.SSH.configFile` setting at it.

Remote - SSH connects with `ssh -F` on that file, which leaves `~/.ssh/config` and its `Match exec`
line unread, so its connections do not regenerate anything. They use the routes from the last `ssh`
run elsewhere. After moving to another network, run any `ssh` command once before connecting from
VS Code.

## Skipping luna

For every host `name` in `zone.ini`, `ssh d.name` connects to it directly without any jumps, in
both modes.

Setting `LUNA_SSH_DIRECT=1` turns routing off for one command. In generator mode `install.sh` then
writes a plain copy of `sshconfig` to `config.inc`. The wrapper exports this variable itself, so an
`ssh` started from inside a connection, such as one in a `ProxyCommand`, runs unrouted.

If luna fails in generator mode, `ssh` prints `Luna failed, trying the previous config` and
connects with the `config.inc` from the last successful run.

## zone.ini reference

All keys of a zone are optional.

`host` lists the hosts in the zone. An entry `name:alias...` gives a host extra names. An alias is
another address of the same host that other zones can jump to, such as a public address, so it may
be unreachable from the host's own zone.

`timezone` and `subnet` decide whether the machine is in the zone. When `timezone` is set, the
local UTC offset must equal it in hours. When `subnet` is set, one of the listed networks must be
the network of a local interface, or contain a gateway when `netifaces-plus` is installed and
`LUNA_STRICT_SUBNET` is unset. A zone with neither key always applies, and every zone that applies
is a starting point for routing.

`arc` lists one-way links from this zone, each in one of these forms.

| Form | Meaning |
|---|---|
| `via:zone:cost` | Jump through `via` into `zone`. |
| `via:zone` | Same, with the default cost of 20. |
| `zone` or `zone:cost` | `zone` is reachable without a jump. |
| `via` or `via:cost` | Jump through `via` into the zone that `via` belongs to. |

`via` is a host or an alias from `host`, or any other hostname when the target zone is written out.
Reaching a host inside a zone adds a cost of 10.

`strict-host = true` stops luna from adding hosts to the zone by itself. Otherwise every host in
the SSH config whose `Hostname` is an IPv4 address inside a zone's subnet joins that zone, and the
hosts whose names start with its name become its aliases.

`hook` names a Python file inside the working directory, which luna imports while loading the
zones.

## Generator mode details

`install.sh` runs luna in `~/.ssh` and skips regeneration when `config.inc` was written in the
last two seconds, or when neither `sshconfig` nor `zone.ini` changed and the network state recorded
in `config.inc.state` still holds. Concurrent connections take turns on `config.inc.lock`, and a
connection that had to wait uses the file the previous one wrote. Options applied by `Match` or
`Include` inside `sshconfig` do not reach the generated routes.

`install.sh` accepts `-c <dir>` (working directory), `-i <file>` (input config, default
`sshconfig`) and `-o <file>` (output, default `~/.ssh/config.inc`).

## Diagnostics

`LUNA_MUTE` silences the scripts and `luna.py`, and `MOON_TRACE` adds timings to the output. In
generator mode the same diagnostics are also written into `config.inc` as comments.

## Development

```sh
uv sync --all-extras
uv run ruff check
uv run ruff format --check
uv run pytest
```

The top-level modules (`luna.py`, `lib.py`, `cfg.py`) hold the command line and zone policy.
`moon/` is the library they build on (the `ssh_config` parser, the routing graph, interface
detection and the lock), and it never imports from the top level. `luna.py` imports lazily because
`Match exec` starts it on every connection.
