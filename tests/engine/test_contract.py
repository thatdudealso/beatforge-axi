from __future__ import annotations

import inspect

import pytest

from engine.base import MusicEngine
from engine.errors import EngineUnavailableError, UnsupportedOperationError
from engine.fake import FakeEngine
from engine.models import CapabilitySet, EngineDescriptor, LicenseId, Operation
from engine.registry import EngineRegistry

EXPECTED_METHODS = {"generate", "repaint", "remix", "stems", "analyze"}


def test_engine_protocol_declares_every_public_operation() -> None:
    methods = {
        name
        for name, _ in inspect.getmembers(MusicEngine, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert methods >= EXPECTED_METHODS


def test_fake_engine_supports_the_complete_contract() -> None:
    engine = FakeEngine()

    assert engine.descriptor.capabilities.supported_operations() == set(Operation)


def test_registry_accepts_mit_and_apache_model_licenses() -> None:
    registry = EngineRegistry()
    registry.register(FakeEngine(name="mit", model_license=LicenseId.MIT))
    registry.register(FakeEngine(name="apache", model_license=LicenseId.APACHE_2_0))

    assert registry.activate("mit").descriptor.name == "mit"
    assert registry.activate("apache").descriptor.name == "apache"


def test_registry_keeps_unconfigured_adapter_but_refuses_activation() -> None:
    registry = EngineRegistry()
    engine = FakeEngine(
        name="musicgen",
        descriptor=EngineDescriptor(
            name="musicgen",
            model="unconfigured",
            code_license=LicenseId.MIT,
            model_license=None,
            checkpoint=None,
            checkpoint_sha256=None,
            provenance_url=None,
            ready=False,
            capabilities=CapabilitySet(generate=True),
        ),
    )
    registry.register(engine)

    assert registry.get("musicgen") is engine
    with pytest.raises(EngineUnavailableError, match="model license"):
        registry.activate("musicgen")


def test_registry_rejects_noncommercial_model_license() -> None:
    registry = EngineRegistry()
    registry.register(FakeEngine(name="musicgen", model_license=LicenseId.CC_BY_NC_4_0))

    with pytest.raises(EngineUnavailableError, match=r"MIT or Apache-2\.0"):
        registry.activate("musicgen")


def test_capability_gate_runs_before_engine_operation() -> None:
    registry = EngineRegistry()
    engine = FakeEngine(
        name="generate-only",
        capabilities=CapabilitySet(generate=True),
    )
    registry.register(engine)

    with pytest.raises(UnsupportedOperationError, match="repaint"):
        registry.for_operation("generate-only", Operation.REPAINT)
    assert engine.calls == []
