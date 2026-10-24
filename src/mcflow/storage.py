"""Small, checksummed JSON records and same-directory atomic replacement."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

WINDOWS = sys.platform == "win32"


class WorkflowError(ValueError):
    """An invalid input or unsafe workflow operation."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError(f"Cannot read valid JSON: {path}: {exc}") from exc


def atomic_text(path, text):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".write-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows indexers/antivirus can briefly hold the destination without delete sharing.
        for attempt in range(7):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if not WINDOWS or getattr(exc, "winerror", None) not in (5, 32) or attempt == 6:
                    raise
                time.sleep(0.025 * 2**attempt)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_record(path, payload):
    envelope = {"payload": payload, "sha256": digest(payload)}
    atomic_text(path, json.dumps(envelope, indent=2, sort_keys=True, allow_nan=False) + "\n")


def read_record(path):
    record = read_json(path)
    if not isinstance(record, dict) or set(record) != {"payload", "sha256"}:
        raise WorkflowError(f"Malformed record: {path}")
    try:
        valid = record["sha256"] == digest(record["payload"])
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"Invalid payload: {path}") from exc
    if not valid:
        raise WorkflowError(f"Checksum mismatch: {path}")
    return record["payload"]
