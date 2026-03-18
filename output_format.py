"""Shared output formatting for human-readable and JSON Lines output.

All commands use this module to support --json-log mode. When JSON mode is active,
structured data is emitted as one JSON object per line (JSON Lines / jsonl format)
instead of human-readable text.

Each JSON line has a "type" field indicating the record type, plus data fields.
"""

import json
import os
import sys
from typing import Any, Dict, Optional


_json_mode = False
_json_file = None  # When set, JSON goes to file; human output still goes to stdout
_real_stdout = sys.stdout  # Preserved before any redirect


def is_json_mode() -> bool:
    return _json_mode


def enable_json_mode(output_file: Optional[str] = None):
    """Enable JSON Lines output.

    If output_file is set, JSON goes to file and human output still prints.
    If output_file is None (stdout), human output is suppressed by redirecting
    stdout to stderr so only JSON lines appear on stdout.
    """
    global _json_mode, _json_file
    _json_mode = True
    if output_file:
        _json_file = open(output_file, "a", encoding="utf-8")
    else:
        # Redirect human print() to stderr so stdout is clean JSON
        sys.stdout = sys.stderr


def emit(record_type: str, data: Dict[str, Any] = None, **kwargs):
    """Emit a JSON Lines record when in JSON mode.

    In human mode, this is a no-op (callers should also print human output).
    In JSON mode, writes one JSON line to stdout or the configured file.
    """
    if not _json_mode:
        return
    record = {"type": record_type}
    if data:
        record.update(data)
    record.update(kwargs)
    line = json.dumps(record, default=str)
    target = _json_file or _real_stdout
    target.write(line + "\n")
    target.flush()


def close():
    """Close the JSON output file if one was opened."""
    global _json_file
    if _json_file:
        _json_file.close()
        _json_file = None


def add_json_arg(parser):
    """Add --json-log argument to an argparse parser."""
    parser.add_argument("--json-log", nargs="?", const="-", default=None,
                        metavar="FILE",
                        help="Output results as JSON Lines (one JSON object per line). "
                             "Optionally specify a file path; defaults to stdout.")


def setup_from_args(args):
    """Call after parsing args to enable JSON mode if --json-log was used."""
    json_log = getattr(args, "json_log", None)
    if json_log is not None:
        if json_log == "-":
            enable_json_mode()
        else:
            enable_json_mode(json_log)
