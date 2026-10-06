"""Fal backup models (listed=False, FAILOVER_MAP, provider inputs)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMAS = ROOT / "tests" / "fixtures" / "fal_schemas"

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")


@pytest.fixture(scope="module")
def srv():
    import server

    return server


def _all_backup_ids(srv):
    ids = set()
    for modes in srv.FAILOVER_MAP.values():
        ids.update(modes.values())
    return sorted(ids)


def test_failover_map_integrity(srv):
    for primary, modes in srv.FAILOVER_MAP.items():
        prim = srv.INTEGRATED_MODELS[primary]
        assert prim["provider"] == "replicate", primary
        for mode, backup_id in modes.items():
            assert mode in {"t", "i"}, (primary, mode)
            bak = srv.INTEGRATED_MODELS[backup_id]
            assert bak["provider"] == "fal", backup_id
            assert bak.get("listed") is False, backup_id
            assert bak.get("backup_for") == primary, backup_id


def test_backups_not_in_integrations(srv):
    import server

    with server.app.test_client() as client:
        data = client.get("/api/integrations").get_json()
    ids = {item["id"] for item in data.get("items") or []}
    for bid in _all_backup_ids(srv):
        assert bid not in ids


def test_backups_not_in_assistant_catalog(srv):
    catalog = srv._catalog_for_prompt(max_chars=500_000)
    for bid in _all_backup_ids(srv):
        assert bid not in catalog


def test_build_input_matches_schema(srv):
    for backup_id in _all_backup_ids(srv):
        schema_path = SCHEMAS / f"{backup_id}.json"
        if not schema_path.is_file():
            pytest.skip(f"no schema fixture for {backup_id}")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        spec = srv.INTEGRATED_MODELS[backup_id]
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        has_image = "i" in (spec.get("inputs") or []) or "image" in (spec.get("inputs") or [])
        image = "https://example.com/ref.png" if has_image else None
        if backup_id == "grok-imagine-video-1-5-i2v-fal":
            image = "https://example.com/ref.png"
        payload = srv._build_provider_input(spec, "test prompt", image, None, None)
        for key in required:
            assert key in payload, f"{backup_id} missing required {key}"
        for key in payload:
            assert key in props, f"{backup_id} unknown key {key} not in schema"
        for key, val in payload.items():
            enum = (props.get(key) or {}).get("enum")
            if enum and isinstance(val, str) and len(enum) > 1:
                assert val in enum, f"{backup_id}.{key}={val!r} not in {enum}"


def test_image_backups_require_image(srv):
    image_modes = [
        bid
        for modes in srv.FAILOVER_MAP.values()
        for mode, bid in modes.items()
        if mode == "i"
    ]
    for backup_id in image_modes:
        spec = srv.INTEGRATED_MODELS[backup_id]
        with pytest.raises(ValueError):
            srv._build_provider_input(spec, "test", None, None, None)


def test_fal_extract_outputs_from_schema_examples(srv):
    for backup_id in _all_backup_ids(srv):
        schema_path = SCHEMAS / f"{backup_id}.json"
        if not schema_path.is_file():
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        example = schema.get("output_example") or {}
        if not example:
            continue
        kind = srv.INTEGRATED_MODELS[backup_id].get("kind") or "image"
        urls = srv._fal_extract_outputs(example, kind)
        assert any(u.startswith("http") for u in urls), backup_id


def test_failover_target_modes(srv):
    assert srv._failover_target("wan-3-0", False) == "wan-3-0-t2v-fal"
    assert srv._failover_target("wan-3-0", True) == "wan-3-0-i2v-fal"
    assert srv._failover_target("grok-imagine-video-1-5", False) is None
    assert srv._failover_target("grok-imagine-video-1-5", True) == "grok-imagine-video-1-5-i2v-fal"
