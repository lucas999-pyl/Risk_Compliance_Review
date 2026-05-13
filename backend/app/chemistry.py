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
    {"cas": "13463-67-7", "ec": "236-675-5", "name_en": "Titanium dioxide", "name_zh": "钛白粉", "aliases": ["rutile"], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "25133-97-5", "ec": None, "name_en": "Acrylic copolymer emulsion", "name_zh": "丙烯酸酯共聚乳液", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "1332-58-7", "ec": "310-127-6", "name_en": "Kaolin (calcined)", "name_zh": "煅烧高岭土", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "57-55-6", "ec": "200-338-0", "name_en": "Propylene glycol", "name_zh": "丙二醇", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "9004-65-3", "ec": None, "name_en": "Hydroxypropyl methylcellulose", "name_zh": "HEUR 增稠剂", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "67762-90-7", "ec": None, "name_en": "Polyether-modified silicone", "name_zh": "聚醚改性硅氧烷流平剂", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "2634-33-5", "ec": "220-120-9", "name_en": "1,2-Benzisothiazolin-3-one (BIT)", "name_zh": "BIT 杀菌剂", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "124-68-5", "ec": "204-709-8", "name_en": "2-Amino-2-methyl-1-propanol (AMP-95)", "name_zh": "AMP-95 pH 调节剂", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "108-88-3", "ec": "203-625-9", "name_en": "Toluene", "name_zh": "甲苯", "aliases": ["methylbenzene"], "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"]},
    {"cas": "141-78-6", "ec": "205-500-4", "name_en": "Ethyl acetate", "name_zh": "乙酸乙酯", "aliases": [], "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"]},
    {"cas": "1330-20-7", "ec": "215-535-7", "name_en": "Xylene (mixed isomers)", "name_zh": "二甲苯（混合异构体）", "aliases": [], "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"]},
    {"cas": "71-36-3", "ec": "200-751-6", "name_en": "n-Butanol", "name_zh": "正丁醇", "aliases": [], "tags": ["china_hazardous_demo", "tsca_active_demo", "flammable_demo"]},
    {"cas": "25068-38-6", "ec": None, "name_en": "Bisphenol A epoxy resin", "name_zh": "双酚 A 型环氧树脂", "aliases": ["E-44"], "tags": ["tsca_active_demo"]},
    {"cas": "7727-43-7", "ec": "231-784-4", "name_en": "Barium sulfate (Barite)", "name_zh": "重晶石粉", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "14807-96-6", "ec": "238-877-9", "name_en": "Talc (asbestos-free)", "name_zh": "滑石粉", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "112945-52-5", "ec": "676-199-5", "name_en": "Fumed silica", "name_zh": "气相二氧化硅", "aliases": ["R972"], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "51274-00-1", "ec": "257-098-5", "name_en": "Pigment Yellow 42", "name_zh": "颜料黄 42", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "139-33-3", "ec": "205-358-3", "name_en": "EDTA disodium salt", "name_zh": "EDTA-2Na", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "1429-50-1", "ec": "215-851-5", "name_en": "EDTMP", "name_zh": "乙二胺四亚甲基膦酸", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
    {"cas": "25155-30-0", "ec": "246-680-4", "name_en": "Sodium dodecylbenzenesulfonate (LAS)", "name_zh": "直链烷基苯磺酸钠", "aliases": [], "tags": ["tsca_active_demo", "low_hazard_demo"]},
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
