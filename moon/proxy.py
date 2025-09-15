import os
import shutil

CONNECT = r'C:\Program Files\Git\mingw64\bin\connect.exe'
NCAT = r'C:\Program Files (x86)\Nmap\ncat.exe'


def has_nc():
    # TODO: check if it's the openbsd variant
    return shutil.which('nc')


def quote(s):
    return '"' + s.replace('\\', '\\\\') + '"'


def get_format() -> str | None:
    if has_nc():
        r = 'nc -X 5 -x {} %h %p'
    elif os.path.exists(CONNECT):
        r = quote(CONNECT) + ' -S {} %h %p'
    elif os.path.exists(NCAT):
        r = quote(NCAT) + ' --proxy-type socks5 --proxy {} %h %p'
    else:
        return None
    return 'ProxyCommand ' + r
