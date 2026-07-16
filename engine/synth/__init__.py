"""Lightweight local synthesis engine.

Generates real, playable audio from text prompts using numpy synthesis.
Produces WAV internally and MP3 via FFmpeg for user artifacts.

This is the development / test engine. It produces real PCM data (not placeholders).
For high-quality models, enable ACE-Step / YuE behind their license+readiness gates.

No proprietary services. Pure local CPU synthesis + ffmpeg post-processing.
"""

from .adapter import SynthEngine

__all__ = ["SynthEngine"]
