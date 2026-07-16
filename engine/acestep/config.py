from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from engine.models import LicenseId

PINNED_UPSTREAM_COMMIT = "6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0"
PINNED_MODEL_REVISION = "19671f406d603126926c1b7e2adc169acbcade22"
PRIMARY_WEIGHT_PATH = Path("acestep-v15-turbo/model.safetensors")
REQUIRED_WEIGHT_PATHS = (
    PRIMARY_WEIGHT_PATH,
    Path("acestep-v15-turbo/silence_latent.pt"),
    Path("vae/diffusion_pytorch_model.safetensors"),
    Path("Qwen3-Embedding-0.6B/model.safetensors"),
    Path("acestep-5Hz-lm-1.7B/model.safetensors"),
)

Device = Literal["auto", "cpu", "cuda", "mps", "xpu"]


@dataclass(frozen=True, slots=True)
class VerifiedWeight:
    """One immutable weight artifact in a locally installed checkpoint bundle."""

    relative_path: Path
    sha256: str


OFFICIAL_WEIGHT_DIGESTS = (
    VerifiedWeight(
        PRIMARY_WEIGHT_PATH,
        "3f6e0797fad420a39bd33979eb6e840e30989e34a3794e843d23b60ec6e422d7",
    ),
    VerifiedWeight(
        Path("acestep-v15-turbo/silence_latent.pt"),
        "a778e9dd942f5e8b2c09c55370782d318834432b03dabbcdf70e6ed49ad6358b",
    ),
    VerifiedWeight(
        Path("vae/diffusion_pytorch_model.safetensors"),
        "da17edb604c40deaf09e9b24974e590d1ca83a374070e5d0884cfa4bed9a99b0",
    ),
    VerifiedWeight(
        Path("Qwen3-Embedding-0.6B/model.safetensors"),
        "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd",
    ),
    VerifiedWeight(
        Path("acestep-5Hz-lm-1.7B/model.safetensors"),
        "f161689da73e5ecefa28ff780d51c2d92a00f056d021d7933c779ed5c6cd7db8",
    ),
)
OFFICIAL_CHECKPOINT_IDENTITY = (
    f"ACE-Step/Ace-Step1.5@{PINNED_MODEL_REVISION}/{PRIMARY_WEIGHT_PATH.as_posix()}"
)
OFFICIAL_PROVENANCE_URL = (
    f"https://huggingface.co/ACE-Step/Ace-Step1.5/tree/{PINNED_MODEL_REVISION}"
)


@dataclass(frozen=True, slots=True)
class AceStepConfig:
    """Adapter-local configuration for the pinned ACE-Step 1.5 boundary."""

    project_root: Path
    checkpoint: str | None = None
    checkpoint_sha256: str | None = None
    verified_weights: tuple[VerifiedWeight, ...] = ()
    model_license: LicenseId | None = None
    provenance_url: str | None = None
    upstream_commit: str = PINNED_UPSTREAM_COMMIT
    config_path: str = "acestep-v15-turbo"
    device: Device = "auto"
    use_mlx_dit: bool = True
    offload_to_cpu: bool = False
    offload_dit_to_cpu: bool = False

    @property
    def checkpoints_dir(self) -> Path:
        return self.project_root / "checkpoints"

    @property
    def checkpoint_file(self) -> Path:
        return self.checkpoints_dir / PRIMARY_WEIGHT_PATH
