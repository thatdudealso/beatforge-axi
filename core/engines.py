from __future__ import annotations

from engine.acestep import AceStepEngine
from engine.acestep.env import config_from_environ
from engine.fake import FakeEngine
from engine.models import CapabilitySet, EngineDescriptor, LicenseId
from engine.registry import EngineRegistry
from engine.synth import SynthEngine


def engine_descriptors() -> dict[str, EngineDescriptor]:
    fake = FakeEngine().descriptor
    fake_generate_only = FakeEngine(
        name="fake-generate-only", capabilities=CapabilitySet(generate=True)
    ).descriptor
    synth = SynthEngine().descriptor
    acestep = AceStepEngine(config_from_environ()).descriptor
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
        for descriptor in (fake, fake_generate_only, synth, musicgen, acestep, yue)
    }


def runtime_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(FakeEngine())
    registry.register(
        FakeEngine(name="fake-generate-only", capabilities=CapabilitySet(generate=True))
    )
    registry.register(SynthEngine())
    registry.register(AceStepEngine(config_from_environ()))
    return registry
