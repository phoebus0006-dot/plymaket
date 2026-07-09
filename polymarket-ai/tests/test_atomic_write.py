from __future__ import annotations

import json
from pathlib import Path

import pytest

from phase0.atomic_write import safe_write, safe_write_json, safe_append_jsonl


class TestSafeWrite:
    def test_writes_text_file(self, tmp_path: Path):
        path = tmp_path / "test.txt"
        safe_write("hello world", path)
        assert path.read_text(encoding="utf-8") == "hello world"

    def test_overwrites_existing(self, tmp_path: Path):
        path = tmp_path / "test.txt"
        safe_write("first", path)
        safe_write("second", path)
        assert path.read_text(encoding="utf-8") == "second"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "a" / "b" / "test.txt"
        safe_write("nested", path)
        assert path.exists()

    def test_writes_binary(self, tmp_path: Path):
        path = tmp_path / "test.bin"
        safe_write(b"\x00\x01\x02", path)
        assert path.read_bytes() == b"\x00\x01\x02"


class TestSafeWriteJson:
    def test_writes_json(self, tmp_path: Path):
        path = tmp_path / "data.json"
        safe_write_json({"key": "value"}, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["key"] == "value"


class TestSafeAppendJsonl:
    def test_append_empty_file(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        safe_append_jsonl({"event": "a"}, path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "a"

    def test_append_to_existing(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        safe_append_jsonl({"event": "a"}, path)
        safe_append_jsonl({"event": "b"}, path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "a"
        assert json.loads(lines[1])["event"] == "b"

    def test_append_three_entries(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        for i in range(3):
            safe_append_jsonl({"idx": i}, path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "x" / "y" / "events.jsonl"
        safe_append_jsonl({"e": 1}, path)
        assert path.exists()
