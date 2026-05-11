from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SubstanceProfile:
    substance_id: str
    name: str
    cas: str
    ec: str | None
    aliases: tuple[str, ...]
    name_en: str | None = None
    name_zh: str | None = None
    tags: frozenset[str] = frozenset()

    @property
    def china_hazardous_demo(self) -> bool:
        return "china_hazardous_demo" in self.tags

    @property
    def tsca_active_demo(self) -> bool:
        return "tsca_active_demo" in self.tags

    @property
    def svhc_demo(self) -> bool:
        return "svhc_demo" in self.tags


DEFAULT_SUBSTANCE_DATA = [
    {
        "cas": "7732-18-5",
        "ec": "231-791-2",
        "name_en": "Water",
        "name_zh": "水",
        "aliases": ["aqua", "dihydrogen monoxide"],
        "tags": ["tsca_active_demo", "low_hazard_demo"],
    },
    {
        "cas": "7647-14-5",
        "ec": "231-598-3",
        "name_en": "Sodium chloride",
        "name_zh": "氯化钠",
        "aliases": ["salt", "sodium salt"],
        "tags": ["tsca_active_demo", "low_hazard_demo"],
    },
    {
        "cas": "64-17-5",
        "ec": "200-578-6",
        "name_en": "Ethanol",
        "name_zh": "乙醇",
        "aliases": ["ethyl alcohol", "alcohol"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"],
    },
    {
        "cas": "67-64-1",
        "ec": "200-662-2",
        "name_en": "Acetone",
        "name_zh": "丙酮",
        "aliases": ["propanone", "dimethyl ketone"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"],
    },
    {
        "cas": "7722-84-1",
        "ec": "231-765-0",
        "name_en": "Hydrogen peroxide",
        "name_zh": "过氧化氢",
        "aliases": ["hydrogen dioxide", "peroxide"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "oxidizer_demo"],
    },
    {
        "cas": "80-05-7",
        "ec": "201-245-8",
        "name_en": "Bisphenol A",
        "name_zh": "双酚A",
        "aliases": ["bpa"],
        "tags": ["svhc_demo"],
    },
    {
        "cas": "7681-52-9",
        "ec": "231-668-3",
        "name_en": "Sodium hypochlorite",
        "name_zh": "次氯酸钠",
        "aliases": ["hypochlorite", "bleach"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "oxidizer_demo", "hypochlorite_demo"],
    },
    {
        "cas": "7647-01-0",
        "ec": "231-595-7",
        "name_en": "Hydrochloric acid",
        "name_zh": "盐酸",
        "aliases": ["hydrogen chloride", "muriatic acid"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "acid_demo"],
    },
    {
        "cas": "71-43-2",
        "ec": "200-753-7",
        "name_en": "Benzene",
        "name_zh": "苯",
        "aliases": ["benzol"],
        "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo", "enterprise_redline_demo"],
    },
]


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_substance_registry(rows: Iterable[dict[str, Any]]) -> dict[str, SubstanceProfile]:
    registry: dict[str, SubstanceProfile] = {}
    for row in rows:
        cas = str(row["cas"]).strip()
        name_zh = _clean_optional(row.get("name_zh"))
        name_en = _clean_optional(row.get("name_en"))
        registry[cas] = SubstanceProfile(
            substance_id=f"cas_{cas.replace('-', '_')}",
            name=name_zh or name_en or cas,
            cas=cas,
            ec=_clean_optional(row.get("ec")),
            aliases=tuple(str(alias).strip() for alias in row.get("aliases", []) if str(alias).strip()),
            name_en=name_en,
            name_zh=name_zh,
            tags=frozenset(str(tag).strip() for tag in row.get("tags", []) if str(tag).strip()),
        )
    return registry


KNOWN_SUBSTANCES: dict[str, SubstanceProfile] = load_substance_registry(DEFAULT_SUBSTANCE_DATA)


def normalize_substance(
    name: str,
    cas: str,
    ec: str | None = None,
    *,
    registry: dict[str, SubstanceProfile] | None = None,
) -> SubstanceProfile:
    known = (registry or KNOWN_SUBSTANCES).get(cas)
    if known:
        return known
    safe_cas = cas.replace("-", "_")
    clean_name = name.strip() or cas
    return SubstanceProfile(
        substance_id=f"cas_{safe_cas}",
        name=clean_name,
        cas=cas,
        ec=ec,
        aliases=(),
        name_en=clean_name if clean_name.isascii() else None,
        name_zh=clean_name if not clean_name.isascii() else None,
        tags=frozenset(),
    )
