"""Importer framework: PromptDraft, the Importer protocol, the registry and the pipeline."""

from promptvault.importers import base
from promptvault.importers.base import (
    Importer,
    ImporterRegistry,
    PromptDraft,
    get,
    names,
    register,
    registry,
)
from promptvault.importers.passthrough import PassthroughImporter

registry.register(PassthroughImporter())

__all__ = [
    "Importer",
    "ImporterRegistry",
    "PassthroughImporter",
    "PromptDraft",
    "base",
    "get",
    "names",
    "register",
    "registry",
]
