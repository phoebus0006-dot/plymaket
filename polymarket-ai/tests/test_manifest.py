from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from phase0.manifest import (
    create_manifest, freeze_manifest, load_manifest,
    verify_manifest, compute_manifest_identity_hash, ManifestRegistry,
)
from phase0.schemas import MarketManifest
from phase0.canonical import compute_hash


class TestManifest:
    def test_create_manifest(self):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        assert manifest.experiment_id == "P0-TEST"
        assert manifest.manifest_hash != ""

    def test_manifest_hash_consistency(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        m1 = create_manifest("P0-TEST", [{"market_id": "M001"}], selection_cutoff=cutoff)
        m2 = create_manifest("P0-TEST", [{"market_id": "M001"}], selection_cutoff=cutoff)
        assert m1.manifest_hash == m2.manifest_hash

    def test_manifest_hash_changes_when_markets_change(self):
        m1 = create_manifest("P0-TEST", [{"market_id": "M001"}])
        m2 = create_manifest("P0-TEST", [{"market_id": "M002"}])
        assert m1.manifest_hash != m2.manifest_hash

    def test_manifest_hash_excludes_created_at(self):
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        m1 = create_manifest("P0-TEST", [{"market_id": "M001"}], selection_cutoff=cutoff)
        h1 = compute_manifest_identity_hash(m1)
        m2 = create_manifest("P0-TEST", [{"market_id": "M001"}], selection_cutoff=cutoff,
                             created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
        h2 = compute_manifest_identity_hash(m2)
        assert h1 == h2

    def test_freeze_and_load(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out_path = freeze_manifest(manifest, tmp_path)
        assert out_path.exists()
        loaded = load_manifest(out_path)
        assert loaded.experiment_id == "P0-TEST"
        ok, _ = verify_manifest(loaded)
        assert ok

    def test_tamper_detection(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out_path = freeze_manifest(manifest, tmp_path)
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["markets"][0]["market_id"] = "TAMPERED"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        loaded = load_manifest(out_path)
        ok, _ = verify_manifest(loaded)
        assert not ok

    def test_naive_timestamp_string_rejected(self):
        with pytest.raises(Exception):
            MarketManifest.model_validate({
                "experiment_id": "P0-TEST",
                "created_at": "2025-06-01T00:00:00",
                "selection_cutoff": "2025-06-01T00:00:00+00:00",
            })

    def test_market_not_in_manifest_rejected(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out_path = freeze_manifest(manifest, tmp_path)
        registry = ManifestRegistry(out_path)
        registry.load()
        assert registry.has_market("M001")
        assert not registry.has_market("M002")


class TestManifestRegistry:
    def test_registry_accepts_market_id(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}, {"market_id": "M002"}])
        out_path = freeze_manifest(manifest, tmp_path)
        registry = ManifestRegistry(out_path)
        registry.load()
        assert registry.has_market("M001")
        assert registry.has_market("M002")

    def test_registry_rejects_tampered_manifest(self, tmp_path: Path):
        manifest = create_manifest("P0-TEST", [{"market_id": "M001"}])
        out_path = freeze_manifest(manifest, tmp_path)
        data = json.loads(out_path.read_text(encoding="utf-8"))
        data["markets"][0]["market_id"] = "TAMPERED"
        out_path.write_text(json.dumps(data), encoding="utf-8")
        registry = ManifestRegistry(out_path)
        with pytest.raises(RuntimeError):
            registry.load()
