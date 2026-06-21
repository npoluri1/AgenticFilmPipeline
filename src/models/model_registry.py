from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import yaml


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    model: str
    cost: str
    quality: str


@dataclass
class ModelCategory:
    id: str
    label: str
    free: list[ModelInfo] = field(default_factory=list)
    premium: list[ModelInfo] = field(default_factory=list)


class ModelRegistry:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml")

        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self.tiers = raw.get("models", {}).get("tiers", {})
        self.default_tier = raw.get("pipeline", {}).get("default_tier", "free")
        self.default_models = raw.get("pipeline", {}).get("default_models", {})

        self.categories: dict[str, ModelCategory] = {}
        for cat_id, cat_data in raw.get("models", {}).get("categories", {}).items():
            free_models = [ModelInfo(id=m["id"], **{k: v for k, v in m.items() if k != "id"}) for m in cat_data.get("free", [])]
            premium_models = [ModelInfo(id=m["id"], **{k: v for k, v in m.items() if k != "id"}) for m in cat_data.get("premium", [])]
            self.categories[cat_id] = ModelCategory(
                id=cat_id,
                label=cat_data["label"],
                free=free_models,
                premium=premium_models,
            )

    def get_category(self, category_id: str) -> Optional[ModelCategory]:
        return self.categories.get(category_id)

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        for cat in self.categories.values():
            for m in cat.free + cat.premium:
                if m.id == model_id:
                    return m
        return None

    def get_models_for_tier(self, category_id: str, tier: str) -> list[ModelInfo]:
        cat = self.categories.get(category_id)
        if not cat:
            return []
        if tier == "free":
            return cat.free
        return cat.free + cat.premium

    def get_default_model_id(self, category_id: str) -> str:
        return self.default_models.get(category_id, "")

    def to_dict(self) -> dict:
        return {
            "tiers": self.tiers,
            "categories": {
                cid: {
                    "id": cid,
                    "label": c.label,
                    "free": [m.__dict__ for m in c.free],
                    "premium": [m.__dict__ for m in c.premium],
                }
                for cid, c in self.categories.items()
            },
        }


registry = ModelRegistry()
