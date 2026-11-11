"""Write one ``NAME=value`` line into an env file (``apikey create --env-file``).

The file is rewritten through a temporary file in the same directory and
``os.replace``, mode 0600; every other line is kept byte for byte. An existing
``NAME=`` (or ``export NAME=``) line is replaced in place, any later duplicate
of it dropped; otherwise the line is appended.
"""

import os
import re
import tempfile

NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def write_env_var(path: str, name: str, value: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValueError(f"{name!r} isn't an environment variable name (A-Z, 0-9 and _, not starting with a digit)")
    if any(c in value for c in "\n\r\"'\\ $#"):
        raise ValueError("the value needs quoting, which this doesn't do")
    target = os.path.realpath(os.path.expanduser(path))
    try:
        with open(target, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        data = b""
    match = re.compile(rb"^[ \t]*(export[ \t]+)?" + name.encode() + rb"[ \t]*=")
    out, replaced = [], False
    for line in data.splitlines(keepends=True):
        m = match.match(line)
        if not m:
            out.append(line)
            continue
        if replaced:
            continue
        ending = line[len(line.rstrip(b"\r\n")):]
        out.append((m.group(1) or b"") + f"{name}={value}".encode() + (ending or b""))
        replaced = True
    if not replaced:
        if out and not out[-1].endswith((b"\n", b"\r")):
            out.append(b"\n")
        out.append(f"{name}={value}\n".encode())
    directory = os.path.dirname(target) or "."
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(b"".join(out))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
