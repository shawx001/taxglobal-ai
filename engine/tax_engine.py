"""Deprecated compatibility shim for tax engine imports.

Import from ``engine`` or the focused ``engine.<module>`` files instead.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .brackets import _bracket_tax_decimal, _long_term_capital_gains_tax, bracket_tax
from .crypto import (
    SUPPORTED_CRYPTO_METHODS,
    _capital_gains_rule_version,
    _crypto_state_not_covered,
    _crypto_state_tax,
    _crypto_tax_estimate,
    _match_crypto_lots,
    _net_capital_gains,
    _sort_crypto_lots,
    _validate_crypto_inputs,
    _validate_crypto_item,
    crypto_gain_estimate,
)
from .dates import _add_one_calendar_year, _parse_iso_date
from .federal import federal_income_tax
from .feie import feie_estimate
from .filing import FILING_ALIASES, SUPPORTED_FILING_STATUSES, _normalize_filing_status
from .money import _decimal_input, _decimal_rule, _money, _money_decimal, _money_quantized
from .nexus import NEXUS_APPROACHING_RATIO, _compare_threshold, nexus_estimate
from .payroll import _combined_payroll, fica_tax, self_employment_tax
from .qbi import qbi_deduction
from .responses import _citations, _invalid_input, _merge_citations, _not_covered, _response
from .rsu import _validate_sale_scenario, rsu_tax_estimate
from .rules_loader import (
    load_capital_gains_rules,
    load_federal_rules,
    load_feie_rules,
    load_fica_rules,
    load_nexus_rules,
    load_qbi_rules,
    load_state_rules,
)
from .state import _state_taxable_base, state_income_tax
from .summary import _summary_rule_version, income_tax_summary

__all__ = [
    "SUPPORTED_FILING_STATUSES",
    "FILING_ALIASES",
    "SUPPORTED_CRYPTO_METHODS",
    "NEXUS_APPROACHING_RATIO",
    "_response",
    "_not_covered",
    "_invalid_input",
    "_money",
    "_money_decimal",
    "_money_quantized",
    "_decimal_rule",
    "_decimal_input",
    "_normalize_filing_status",
    "_citations",
    "_merge_citations",
    "_bracket_tax_decimal",
    "_long_term_capital_gains_tax",
    "_parse_iso_date",
    "_add_one_calendar_year",
    "_summary_rule_version",
    "bracket_tax",
    "federal_income_tax",
    "fica_tax",
    "self_employment_tax",
    "_combined_payroll",
    "qbi_deduction",
    "feie_estimate",
    "state_income_tax",
    "_state_taxable_base",
    "income_tax_summary",
    "_capital_gains_rule_version",
    "_net_capital_gains",
    "_validate_crypto_item",
    "_validate_crypto_inputs",
    "_sort_crypto_lots",
    "_match_crypto_lots",
    "_crypto_tax_estimate",
    "_crypto_state_not_covered",
    "_crypto_state_tax",
    "crypto_gain_estimate",
    "_validate_sale_scenario",
    "rsu_tax_estimate",
    "_compare_threshold",
    "nexus_estimate",
    "date",
    "ROUND_HALF_UP",
    "Decimal",
    "Any",
    "load_capital_gains_rules",
    "load_federal_rules",
    "load_feie_rules",
    "load_fica_rules",
    "load_nexus_rules",
    "load_qbi_rules",
    "load_state_rules",
]
