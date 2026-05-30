"""embody.core — plugin internals: config loader, state transport, voice.

These modules are persona- and hardware-agnostic. Persona/voice/audio/face
settings come from ``config.yaml`` (see ``core.config``); hardware is handled by
the optional, auto-detected backends in the sibling ``embody.backends`` package.
"""
