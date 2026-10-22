"""A reader for the small part of TOML that topics.toml uses, for Python 3.10.

Python 3.11+ reads TOML with the standard library's `tomllib`, and this
module is not used there. Python 3.10 (the version on Ubuntu 22.04) has no
TOML reader, so this one covers exactly what the topics file needs:

    # comments, on their own line or after a value
    [table] and [dotted.table] headers
    key = 'literal string'     (no escapes: ideal for PubMed queries with " in them)
    key = "basic string"       (with the usual escapes: \\" \\\\ \\n \\t)

Anything else (numbers, lists, multi-line strings, ...) is rejected with the
line number, rather than read wrongly.
"""

import re

_KEY = re.compile(r"[A-Za-z0-9_-]+")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


class TOMLLiteError(ValueError):
    pass


def _fail(lineno, msg):
    raise TOMLLiteError(f"topics file line {lineno}: {msg} "
                        f"(Python 3.10 reads only strings, tables and comments; "
                        f"Python 3.11+ reads all of TOML)")


def _string(s, lineno):
    """Parse one string at the start of s. Returns (value, rest of line)."""
    if s.startswith(("'''", '"""')):
        _fail(lineno, "multi-line strings are not supported")
    if s.startswith("'"):
        end = s.find("'", 1)
        if end < 0:
            _fail(lineno, "unterminated string")
        return s[1:end], s[end + 1:]
    if s.startswith('"'):
        out, i = [], 1
        while i < len(s):
            c = s[i]
            if c == '"':
                return "".join(out), s[i + 1:]
            if c == "\\":
                if i + 1 >= len(s) or s[i + 1] not in _ESCAPES:
                    _fail(lineno, "unsupported escape in string")
                out.append(_ESCAPES[s[i + 1]])
                i += 2
                continue
            out.append(c)
            i += 1
        _fail(lineno, "unterminated string")
    _fail(lineno, "value must be a quoted string")


def loads(text):
    root = {}
    table = root
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            m = re.fullmatch(r"\[\s*([^\[\]]+?)\s*\]\s*(#.*)?", line)
            if not m or line.startswith("[["):
                _fail(lineno, "bad table header")
            table = root
            for part in m.group(1).split("."):
                part = part.strip()
                if not _KEY.fullmatch(part):
                    _fail(lineno, f"bad table name {part!r}")
                table = table.setdefault(part, {})
                if not isinstance(table, dict):
                    _fail(lineno, f"{part!r} is already a value, not a table")
            continue
        key, eq, rest = line.partition("=")
        key = key.strip()
        if not eq or not _KEY.fullmatch(key):
            _fail(lineno, "expected key = value")
        if key in table:
            _fail(lineno, f"duplicate key {key!r}")
        value, after = _string(rest.strip(), lineno)
        after = after.strip()
        if after and not after.startswith("#"):
            _fail(lineno, "unexpected text after the value")
        table[key] = value
    return root
