"""Importer framework: PromptDraft, the Importer protocol, the registry and the pipeline."""

import importlib.util

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
from promptvault.importers.clipboard import ClipboardImporter
from promptvault.importers.csv_import import CsvImporter
from promptvault.importers.json_import import JsonImporter
from promptvault.importers.markdown_import import MarkdownImporter
from promptvault.importers.passthrough import PassthroughImporter
from promptvault.importers.xlsx_import import XlsxImporter

for _importer in (
    PassthroughImporter(),
    JsonImporter(),
    CsvImporter(),
    MarkdownImporter(),
    ClipboardImporter(),
):
    registry.register(_importer)

if importlib.util.find_spec("openpyxl") is not None:
    registry.register(XlsxImporter())
else:
    registry.mark_unavailable(
        XlsxImporter.name,
        XlsxImporter.description,
        "install the optional extra: pip install 'promptvault[xlsx]'",
    )

__all__ = [
    "ClipboardImporter",
    "CsvImporter",
    "Importer",
    "ImporterRegistry",
    "JsonImporter",
    "MarkdownImporter",
    "PassthroughImporter",
    "PromptDraft",
    "XlsxImporter",
    "base",
    "get",
    "names",
    "register",
    "registry",
]
