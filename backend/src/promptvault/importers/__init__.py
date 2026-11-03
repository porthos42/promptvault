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
from promptvault.importers.github import GithubImporter
from promptvault.importers.huggingface import HuggingFaceImporter
from promptvault.importers.json_import import JsonImporter
from promptvault.importers.markdown_import import MarkdownImporter
from promptvault.importers.passthrough import PassthroughImporter
from promptvault.importers.url import UrlImporter
from promptvault.importers.xlsx_import import XlsxImporter

for _importer in (
    PassthroughImporter(),
    JsonImporter(),
    CsvImporter(),
    MarkdownImporter(),
    ClipboardImporter(),
    GithubImporter(),
    UrlImporter(),
    HuggingFaceImporter(),
):
    registry.register(_importer)

if importlib.util.find_spec("openpyxl") is not None:
    registry.register(XlsxImporter())
else:
    registry.mark_unavailable(
        XlsxImporter.name,
        XlsxImporter.description,
        "install the optional extra: pip install 'prompt-vault[xlsx]'",
    )

__all__ = [
    "ClipboardImporter",
    "CsvImporter",
    "GithubImporter",
    "HuggingFaceImporter",
    "Importer",
    "ImporterRegistry",
    "JsonImporter",
    "MarkdownImporter",
    "PassthroughImporter",
    "PromptDraft",
    "UrlImporter",
    "XlsxImporter",
    "base",
    "get",
    "names",
    "register",
    "registry",
]
