"""Skill registry: single source of truth for available tax skills."""

from __future__ import annotations

from backend.skills.analyze_rsu import AnalyzeRsu
from backend.skills.assess_feie import AssessFeie
from backend.skills.base import TaxSkill
from backend.skills.calculate_income_tax import CalculateIncomeTax
from backend.skills.detect_nexus import DetectNexus
from backend.skills.track_crypto import TrackCrypto

_SKILLS: dict[str, TaxSkill] = {}


def _register_defaults() -> None:
    for skill_cls in (CalculateIncomeTax, AssessFeie, AnalyzeRsu, TrackCrypto, DetectNexus):
        instance = skill_cls()
        _SKILLS[instance.name] = instance


def get_skill(name: str) -> TaxSkill | None:
    """Return a Skill by name, or None if not found."""

    if not _SKILLS:
        _register_defaults()
    return _SKILLS.get(name)


def get_all_skills() -> list[TaxSkill]:
    """Return all registered Skills."""

    if not _SKILLS:
        _register_defaults()
    return list(_SKILLS.values())


def get_all_tools() -> list[TaxSkill]:
    """Return all Skills as LangChain tools for future LangGraph integration."""

    return get_all_skills()
