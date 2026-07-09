from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from .schemas import ManifestMarketEntry, MarketManifest


def create_manifest(
    experiment_id: str,
    markets: list[dict[str, Any]] | None = None,
    selection_cutoff: datetime | None = None,
    created_at: datetime | None = None,
) -> MarketManifest:
    """Create a MarketManifest from simple inputs."""
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if selection_cutoff is None:
        selection_cutoff = created_at
    market_entries = [
        ManifestMarketEntry(
            market_id=m.get("market_id", ""),
            question=m.get("question", ""),
            description=m.get("description", ""),
            tags=m.get("tags", []),
        )
        for m in (markets or [])
    ]
    manifest = MarketManifest(
        experiment_id=experiment_id,
        created_at=created_at,
        selection_cutoff=selection_cutoff,
        markets=market_entries,
    )
    manifest.manifest_hash = compute_manifest_identity_hash(manifest)
    manifest.manifest_artifact_hash = compute_manifest_artifact_hash(manifest)
    return manifest


def freeze_manifest(manifest: MarketManifest, output_dir: str | Path) -> Path:
    """Atomically write a MarketManifest to disk as JSON, returns the path.

    Raises FileExistsError if the target already exists (immutable freeze).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "manifest.json"
    if path.is_file():
        raise FileExistsError(f"frozen manifest already exists: {path}")
    _atomic_write(path, manifest.model_dump_json(indent=2).encode("utf-8"))
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_manifest(path: str | Path) -> MarketManifest:
    """Load a MarketManifest from a JSON file."""
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return MarketManifest(**raw)


def verify_manifest(manifest: MarketManifest, check_artifact: bool = True) -> tuple[bool, str]:
    """Verify manifest integrity.

    Returns (ok, details) where details describes PASS/FAIL for each check.
    """
    details: list[str] = []

    if manifest.manifest_hash:
        expected_id = compute_manifest_identity_hash(manifest)
        id_ok = manifest.manifest_hash == expected_id
        details.append(f"identity_hash: {'PASS' if id_ok else 'FAIL'}")
        if not id_ok:
            return False, "; ".join(details)
    else:
        details.append("identity_hash: SKIP (empty)")

    if check_artifact and manifest.manifest_artifact_hash:
        expected_art = compute_manifest_artifact_hash(manifest)
        art_ok = manifest.manifest_artifact_hash == expected_art
        details.append(f"artifact_hash: {'PASS' if art_ok else 'FAIL'}")
        if not art_ok:
            return False, "; ".join(details)
    else:
        details.append("artifact_hash: SKIP (empty)")

    return True, "; ".join(details)


def compute_manifest_identity_hash(manifest: MarketManifest) -> str:
    """Compute a hash over the identity-relevant fields (excludes created_at, manifest_hash)."""
    raw = {
        "experiment_id": manifest.experiment_id,
        "markets": [
            {"market_id": m.market_id, "question": m.question}
            for m in manifest.markets
        ],
        "selection_cutoff": manifest.selection_cutoff.isoformat(),
    }
    return sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()


def compute_manifest_artifact_hash(manifest: MarketManifest) -> str:
    """Compute a hash over the canonical artifact payload.

    Excludes self-referential fields (manifest_hash, manifest_artifact_hash)
    to avoid the hash-of-hash problem.
    """
    raw = manifest.model_dump(mode="json")
    for field in ("manifest_hash", "manifest_artifact_hash"):
        raw.pop(field, None)
    return sha256(
        json.dumps(raw, sort_keys=True).encode("utf-8")
    ).hexdigest()


def find_manifest_path(experiments_root: str, experiment_id: str) -> str | None:
    """Search for a manifest file under experiments_root/experiment_id/.

    Tries manifest.json first, then manifest.yaml, then manifest.yml.
    Returns the full path as a string, or None if not found.
    """
    base = Path(experiments_root) / experiment_id
    for candidate in ("manifest.json", "manifest.yaml", "manifest.yml"):
        p = base / candidate
        if p.is_file():
            return str(p)
    return None


class ManifestRegistry:
    """Loads and caches a frozen MarketManifest on disk."""

    def __init__(self, manifest_path: str | Path) -> None:
        self._path = Path(manifest_path)
        self._manifest: MarketManifest | None = None

    def load(self) -> MarketManifest:
        if self._manifest is not None:
            return self._manifest
        if not self._path.is_file():
            raise FileNotFoundError(f"manifest not found: {self._path}")
        raw: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        self._manifest = MarketManifest(**raw)
        self.verify_or_fail()
        return self._manifest

    @property
    def manifest(self) -> MarketManifest:
        if self._manifest is None:
            return self.load()
        return self._manifest

    def get_market(self, market_id: str) -> ManifestMarketEntry | None:
        for m in self.manifest.markets:
            if m.market_id == market_id:
                return m
        return None

    def has_market(self, market_id: str) -> bool:
        return self.get_market(market_id) is not None

    def verify_manifest_hash(self) -> bool:
        m = self.manifest
        if not m.manifest_hash:
            return True
        expected = compute_manifest_identity_hash(m)
        return m.manifest_hash == expected

    def verify_artifact_hash(self) -> bool:
        m = self.manifest
        if not m.manifest_artifact_hash:
            return True
        expected = compute_manifest_artifact_hash(m)
        return m.manifest_artifact_hash == expected

    def verify_or_fail(self) -> None:
        if not self.verify_manifest_hash():
            raise RuntimeError("manifest identity hash mismatch")
        if not self.verify_artifact_hash():
            raise RuntimeError("manifest artifact hash mismatch")
