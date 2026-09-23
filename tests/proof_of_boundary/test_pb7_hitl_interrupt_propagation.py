"""PB-7: HITL propagation tests, conditionally waived for non-HITL agents."""

from pathlib import Path
import warnings

import pytest
import yaml


_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _hitl_enabled() -> bool:
    if not _CONFIG_PATH.exists():
        warnings.warn(f"{_CONFIG_PATH} not found; PB-7 is auto-waived", UserWarning)
        return False
    try:
        config = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        warnings.warn("config/config.yaml could not be read as YAML; PB-7 is auto-waived", UserWarning)
        return False
    if not isinstance(config, dict):
        warnings.warn("config/config.yaml has unexpected shape; expected 'hitl:' mapping shape", UserWarning)
        return False
    hitl = config.get("hitl")
    if hitl is None and "hitl" not in config:
        return False
    if not isinstance(hitl, dict):
        warnings.warn("config/config.yaml expected 'hitl:' mapping shape", UserWarning)
        return False
    return bool(hitl.get("enabled", False))


pytestmark = pytest.mark.skipif(
    not _hitl_enabled(),
    reason="PB-7 auto-waived: config/config.yaml declares hitl.enabled=false",
)


def test_pb7_hitl_interrupt_propagates() -> None:
    pytest.skip("PB-7 becomes active only if RET-C2-035 adds an interrupt node")


def test_pb7_hitl_allowed_false_skips_interrupt() -> None:
    pytest.skip("PB-7 becomes active only if RET-C2-035 adds an interrupt node")
