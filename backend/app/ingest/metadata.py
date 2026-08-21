"""Identifying a document: which policy it is, and which vintage.

The corpus contains the same policy twice. `Global AML CFT CPF and KYC Policy -
2023.pdf` and `A-INST-2025-01- Encl. Global AML CFT CPF and KYC Policy.pdf` are
two vintages of one document, and the same is true of the Sanctions policy.
Their clauses are near-identical in wording and different in substance, so a
retriever with no notion of vintage will return whichever embeds marginally
closer and the model will state it as current fact.

That is the failure this module exists to prevent. It answers two questions
about every document:

**Which policy family is this?** — so two vintages can be recognised as rivals
rather than as unrelated documents that happen to be similar.

**What year is it?** — so the newer one can be preferred, and a genuine
disagreement between them surfaced rather than silently resolved.

Both are derived from the filename, because the filenames are the only place
the distinction is reliably recorded: `A-INST-2025-01` is a circular reference
carrying the year, and `- 2023` is a suffix somebody added by hand. The
document's own cover page often states neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: `A-INST-2025-01- Encl.` — a circular reference the policy was issued under.
#: The year in it is the issue year, and is the most reliable date in the corpus.
_CIRCULAR = re.compile(r"^([A-Z]-[A-Z]+-(\d{4})-\d+)[-\s]*(?:Encl\.?)?\s*", re.IGNORECASE)

#: Editorial noise that is not part of the policy's identity.
_NOISE = (
    re.compile(r"\s*[-–]\s*Portal\s+[Vv]ersion\s*", re.IGNORECASE),
    re.compile(r"\s*\(\d+\)\s*$"),          # browser download suffix
    re.compile(r"\s*[-–]\s*Encl\.?\s*", re.IGNORECASE),
)

#: A year appearing as a standalone token, with or without a separator before it.
_YEAR = re.compile(r"(?:^|[\s\-–_])((?:19|20)\d{2})(?=$|[\s\-–_)])")

_SEPARATORS = re.compile(r"[^a-z0-9]+")

#: Expansions applied before slugging so two vintages of one policy agree.
#: Deliberately tiny and specific to this corpus — a general synonym list would
#: start merging genuinely different documents.
_CANON = {
    "afpad": "approval framework for policies and associated documents",
    "bcp": "business continuity",
    "kyc": "know your customer",
}


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    """What a document is, for retrieval and for citation."""

    #: Stable across re-ingests, and what a chunk points back to.
    doc_id: str
    #: Shown to the reader in a citation. The filename, tidied.
    title: str
    #: Shared by every vintage of the same policy.
    policy_family: str
    #: None when the filename records no year and none could be inferred.
    year: int | None
    #: The circular this was issued under, where there is one.
    circular: str = ""

    @property
    def is_dated(self) -> bool:
        return self.year is not None


def _slug(text: str) -> str:
    return _SEPARATORS.sub("-", text.lower()).strip("-")


def identify(pdf_name: str) -> DocumentIdentity:
    """Derive identity from a filename.

    Order matters: the circular prefix is taken first because it carries the
    year, and removing it afterwards would throw that away — `A-INST-2025-01-
    Encl. Sanctions Compliance Policy.pdf` records 2025 nowhere else.
    """
    stem = Path(pdf_name).stem.strip()

    circular = ""
    year: int | None = None
    if match := _CIRCULAR.match(stem):
        circular = match.group(1).upper()
        year = int(match.group(2))
        stem = stem[match.end():]

    for pattern in _NOISE:
        stem = pattern.sub(" ", stem)

    # Any remaining year belongs to the document, not to its name.
    if found := _YEAR.findall(stem):
        if year is None:
            year = int(found[-1])
        stem = _YEAR.sub(" ", stem)

    title = re.sub(r"\s{2,}", " ", stem).strip(" -–_")

    family_source = title.lower()
    for short, long in _CANON.items():
        family_source = re.sub(rf"\b{short}\b", long, family_source)

    return DocumentIdentity(
        doc_id=_slug(Path(pdf_name).stem),
        title=title or Path(pdf_name).stem,
        policy_family=_slug(family_source),
        year=year,
        circular=circular,
    )


def group_by_family(names: list[str]) -> dict[str, list[DocumentIdentity]]:
    """Documents sharing a policy family, newest first.

    A family with more than one member is a vintage conflict waiting to happen:
    retrieval must prefer the newest and say so when the older one genuinely
    disagrees, rather than picking whichever embedded closer.
    """
    families: dict[str, list[DocumentIdentity]] = {}
    for name in names:
        identity = identify(name)
        families.setdefault(identity.policy_family, []).append(identity)
    for members in families.values():
        members.sort(key=lambda d: (d.year or 0), reverse=True)
    return families
