from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def safe_write(data: str | bytes, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    encoding = None if isinstance(data, bytes) else "utf-8"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, mode, encoding=encoding) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_write_json(data: Any, path: str | Path, indent: int = 2) -> None:
    content = json.dumps(data, indent=indent, ensure_ascii=False, default=str) + "\n"
    safe_write(content, path)


def safe_append_jsonl(entry: dict[str, Any], path: str | Path) -> None:
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
        with open(path, "ab") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            existing = b""
            if path.exists():
                with open(path, "rb") as f:
                    existing = f.read()
            with os.fdopen(fd, "wb") as f:
                if existing:
                    f.write(existing)
                f.write(line.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(path))
            _fsync_dir(path.parent)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
