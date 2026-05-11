from __future__ import annotations

from app.chemistry import SubstanceProfile, load_substance_registry, normalize_substance


def test_load_substance_registry_normalizes_demo_master_data() -> None:
    registry = load_substance_registry(
        [
            {
                "cas": "64-17-5",
                "ec": "200-578-6",
                "name_en": "Ethanol",
                "name_zh": "乙醇",
                "aliases": ["ethyl alcohol", "alcohol"],
                "tags": ["china_hazardous_demo", "tsca_active_demo"],
            },
            {
                "cas": "80-05-7",
                "ec": "201-245-8",
                "name_en": "Bisphenol A",
                "name_zh": "双酚A",
                "aliases": ["BPA"],
                "tags": ["svhc_demo"],
            },
        ]
    )

    ethanol = normalize_substance("ethyl alcohol", "64-17-5", registry=registry)
    unknown = normalize_substance("Research intermediate", "123456-78-9", registry=registry)

    assert isinstance(ethanol, SubstanceProfile)
    assert ethanol.name == "乙醇"
    assert ethanol.name_en == "Ethanol"
    assert ethanol.aliases == ("ethyl alcohol", "alcohol")
    assert ethanol.tags == frozenset({"china_hazardous_demo", "tsca_active_demo"})
    assert ethanol.china_hazardous_demo is True
    assert unknown.name == "Research intermediate"
    assert unknown.tags == frozenset()
