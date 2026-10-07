from __future__ import annotations

from engine.models import CapabilitySet, EngineDescriptor, LicenseId
from engine.registry import EngineRegistry
from engine.synth import SynthEngine


def engine_descriptors() -> dict[str, EngineDescriptor]:
    synth = SynthEngine().descriptor
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
    return {descriptor.name: descriptor for descriptor in (synth, musicgen, acestep, yue)}


def runtime_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(SynthEngine())
    return registry
