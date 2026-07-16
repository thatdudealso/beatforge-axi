from __future__ import annotations

from engine.fake import FakeEngine
from engine.models import CapabilitySet, EngineDescriptor, LicenseId
from engine.registry import EngineRegistry


def engine_descriptors() -> dict[str, EngineDescriptor]:
    fake = FakeEngine().descriptor
    fake_generate_only = FakeEngine(
        name="fake-generate-only", capabilities=CapabilitySet(generate=True)
    ).descriptor
    musicgen = EngineDescriptor(
        name="musicgen",
        model="unconfigured",
        code_license=LicenseId.MIT,
        model_license=None,
        checkpoint=None,
        checkpoint_sha256=None,
        provenance_url=None,
        ready=False,
        capabilities=CapabilitySet(generate=True),
    )
    acestep = EngineDescriptor(
        name="acestep",
        model="acestep-v15-turbo",
        code_license=LicenseId.MIT,
        model_license=None,
        checkpoint=None,
        checkpoint_sha256=None,
        provenance_url=None,
        ready=False,
        capabilities=CapabilitySet(generate=True),
    )
    yue = EngineDescriptor(
        name="yue",
        model="unconfigured",
        code_license=LicenseId.APACHE_2_0,
        model_license=None,
        checkpoint=None,
        checkpoint_sha256=None,
        provenance_url=None,
        ready=False,
        capabilities=CapabilitySet(generate=True, remix=True),
    )
    return {
        descriptor.name: descriptor
        for descriptor in (fake, fake_generate_only, musicgen, acestep, yue)
    }


def runtime_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(FakeEngine())
    registry.register(
        FakeEngine(name="fake-generate-only", capabilities=CapabilitySet(generate=True))
    )
    return registry
