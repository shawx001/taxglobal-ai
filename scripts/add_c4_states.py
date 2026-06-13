"""Add C4 complex states (AL/CT/DC/MN/WI) to us_states.json."""

import json
import pathlib
import copy

ROOT = pathlib.Path(__file__).resolve().parent.parent

def same_all(brackets):
    """Return dict mapping all 5 filing statuses to the same bracket list."""
    return {
        "single": brackets,
        "married_filing_jointly": brackets,
        "married_filing_separately": brackets,
        "head_of_household": brackets,
        "qualifying_surviving_spouse": brackets,
    }

# ---------- AL: 3 brackets, federal tax subtraction ----------
AL = {
    "income_tax_type": "progressive",
    "status": "effective",
    "effective_date": "2025-01-01",
    "brackets": {
        "single": [
            {"up_to": 500, "rate": 0.02},
            {"up_to": 3000, "rate": 0.04},
            {"up_to": None, "rate": 0.05},
        ],
        "married_filing_jointly": [
            {"up_to": 1000, "rate": 0.02},
            {"up_to": 6000, "rate": 0.04},
            {"up_to": None, "rate": 0.05},
        ],
        "married_filing_separately": [
            {"up_to": 500, "rate": 0.02},
            {"up_to": 3000, "rate": 0.04},
            {"up_to": None, "rate": 0.05},
        ],
        "head_of_household": [
            {"up_to": 1000, "rate": 0.02},
            {"up_to": 6000, "rate": 0.04},
            {"up_to": None, "rate": 0.05},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 1000, "rate": 0.02},
            {"up_to": 6000, "rate": 0.04},
            {"up_to": None, "rate": 0.05},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 4500,
            "married_filing_jointly": 11500,
            "married_filing_separately": 5750,
            "head_of_household": 8200,
            "qualifying_surviving_spouse": 10000,
        },
        "federal_tax_subtraction": {
            "phaseout_table": {
                "single": [{"agi_up_to": None, "limit": 999999999}],
                "married_filing_jointly": [{"agi_up_to": None, "limit": 999999999}],
                "married_filing_separately": [{"agi_up_to": None, "limit": 999999999}],
                "head_of_household": [{"agi_up_to": None, "limit": 999999999}],
                "qualifying_surviving_spouse": [{"agi_up_to": None, "limit": 999999999}],
            },
        },
    },
    "source_ids": ["al_dor_income_tax_2025"],
    "notes": "AL 2025; 3 brackets (2%/4%/5%). Standard deduction ($3,000/$8,500) + personal exemption ($1,500/$3,000) combined; standard deduction phaseout NOT modeled. Federal tax subtraction with no cap. Dependent exemption ($1,000 or $300 by income) not modeled.",
}

# ---------- CT: 7 brackets, no standard deduction ----------
CT = {
    "income_tax_type": "progressive",
    "status": "effective",
    "effective_date": "2025-01-01",
    "brackets": {
        "single": [
            {"up_to": 10000, "rate": 0.02},
            {"up_to": 50000, "rate": 0.045},
            {"up_to": 100000, "rate": 0.055},
            {"up_to": 200000, "rate": 0.06},
            {"up_to": 250000, "rate": 0.065},
            {"up_to": 500000, "rate": 0.069},
            {"up_to": None, "rate": 0.0699},
        ],
        "married_filing_jointly": [
            {"up_to": 20000, "rate": 0.02},
            {"up_to": 100000, "rate": 0.045},
            {"up_to": 200000, "rate": 0.055},
            {"up_to": 400000, "rate": 0.06},
            {"up_to": 500000, "rate": 0.065},
            {"up_to": 1000000, "rate": 0.069},
            {"up_to": None, "rate": 0.0699},
        ],
        "married_filing_separately": [
            {"up_to": 10000, "rate": 0.02},
            {"up_to": 50000, "rate": 0.045},
            {"up_to": 100000, "rate": 0.055},
            {"up_to": 200000, "rate": 0.06},
            {"up_to": 250000, "rate": 0.065},
            {"up_to": 500000, "rate": 0.069},
            {"up_to": None, "rate": 0.0699},
        ],
        "head_of_household": [
            {"up_to": 16000, "rate": 0.02},
            {"up_to": 80000, "rate": 0.045},
            {"up_to": 160000, "rate": 0.055},
            {"up_to": 320000, "rate": 0.06},
            {"up_to": 400000, "rate": 0.065},
            {"up_to": 800000, "rate": 0.069},
            {"up_to": None, "rate": 0.0699},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 20000, "rate": 0.02},
            {"up_to": 100000, "rate": 0.045},
            {"up_to": 200000, "rate": 0.055},
            {"up_to": 400000, "rate": 0.06},
            {"up_to": 500000, "rate": 0.065},
            {"up_to": 1000000, "rate": 0.069},
            {"up_to": None, "rate": 0.0699},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 0,
            "married_filing_jointly": 0,
            "married_filing_separately": 0,
            "head_of_household": 0,
            "qualifying_surviving_spouse": 0,
        },
    },
    "source_ids": ["ct_drs_income_tax_2025"],
    "notes": "CT 2025; 7 brackets (2%-6.99%). No standard deduction. Personal exemptions ($15,000/$24,000) are tax credits, NOT modeled. Benefit recapture (Tables C/D) NOT modeled--understates tax for high earners.",
}

# ---------- DC: 7 brackets, uniform, standard deduction ----------
DC = {
    "income_tax_type": "progressive",
    "status": "effective",
    "effective_date": "2025-01-01",
    "brackets": same_all([
        {"up_to": 10000, "rate": 0.04},
        {"up_to": 40000, "rate": 0.06},
        {"up_to": 60000, "rate": 0.065},
        {"up_to": 250000, "rate": 0.085},
        {"up_to": 500000, "rate": 0.0925},
        {"up_to": 1000000, "rate": 0.0975},
        {"up_to": None, "rate": 0.1075},
    ]),
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 15000,
            "married_filing_jointly": 30000,
            "married_filing_separately": 15000,
            "head_of_household": 22500,
            "qualifying_surviving_spouse": 30000,
        },
    },
    "source_ids": ["dc_otr_income_tax_2025"],
    "notes": "DC 2025; 7 brackets (4%-10.75%), uniform. Standard deduction $15,000/$30,000. Personal exemptions eliminated for 2025.",
}

# ---------- MN: 4 brackets, per-status ----------
MN = {
    "income_tax_type": "progressive",
    "status": "effective",
    "effective_date": "2025-01-01",
    "brackets": {
        "single": [
            {"up_to": 32570, "rate": 0.0535},
            {"up_to": 106990, "rate": 0.068},
            {"up_to": 198630, "rate": 0.0785},
            {"up_to": None, "rate": 0.0985},
        ],
        "married_filing_jointly": [
            {"up_to": 47620, "rate": 0.0535},
            {"up_to": 189180, "rate": 0.068},
            {"up_to": 330410, "rate": 0.0785},
            {"up_to": None, "rate": 0.0985},
        ],
        "married_filing_separately": [
            {"up_to": 23810, "rate": 0.0535},
            {"up_to": 94590, "rate": 0.068},
            {"up_to": 165205, "rate": 0.0785},
            {"up_to": None, "rate": 0.0985},
        ],
        "head_of_household": [
            {"up_to": 40100, "rate": 0.0535},
            {"up_to": 161130, "rate": 0.068},
            {"up_to": 264050, "rate": 0.0785},
            {"up_to": None, "rate": 0.0985},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 47620, "rate": 0.0535},
            {"up_to": 189180, "rate": 0.068},
            {"up_to": 330410, "rate": 0.0785},
            {"up_to": None, "rate": 0.0985},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 14950,
            "married_filing_jointly": 29900,
            "married_filing_separately": 14950,
            "head_of_household": 22500,
            "qualifying_surviving_spouse": 29900,
        },
    },
    "source_ids": ["mn_dor_income_tax_2025"],
    "notes": "MN 2025; 4 brackets (5.35%-9.85%), indexed. Standard deduction $14,950/$29,900. 1% net investment income surtax on >$1M NOT modeled (applies to investment income only, not wage income). Dependent exemption ($5,200/dependent) not modeled.",
}

# ---------- WI: 4 brackets, per-status ----------
WI = {
    "income_tax_type": "progressive",
    "status": "effective",
    "effective_date": "2025-01-01",
    "brackets": {
        "single": [
            {"up_to": 14680, "rate": 0.035},
            {"up_to": 29370, "rate": 0.044},
            {"up_to": 323290, "rate": 0.053},
            {"up_to": None, "rate": 0.0765},
        ],
        "married_filing_jointly": [
            {"up_to": 19580, "rate": 0.035},
            {"up_to": 39150, "rate": 0.044},
            {"up_to": 431060, "rate": 0.053},
            {"up_to": None, "rate": 0.0765},
        ],
        "married_filing_separately": [
            {"up_to": 9790, "rate": 0.035},
            {"up_to": 19580, "rate": 0.044},
            {"up_to": 215530, "rate": 0.053},
            {"up_to": None, "rate": 0.0765},
        ],
        "head_of_household": [
            {"up_to": 14680, "rate": 0.035},
            {"up_to": 29370, "rate": 0.044},
            {"up_to": 323290, "rate": 0.053},
            {"up_to": None, "rate": 0.0765},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 19580, "rate": 0.035},
            {"up_to": 39150, "rate": 0.044},
            {"up_to": 431060, "rate": 0.053},
            {"up_to": None, "rate": 0.0765},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 14260,
            "married_filing_jointly": 26510,
            "married_filing_separately": 12630,
            "head_of_household": 18220,
            "qualifying_surviving_spouse": 25810,
        },
    },
    "source_ids": ["wi_dor_income_tax_2025"],
    "notes": "WI 2025; 4 brackets (3.50%-7.65%). Standard deduction ($13,560/$25,110) + personal exemption ($700/person) combined; sliding-scale standard deduction phaseout NOT modeled--overstates deduction for higher earners.",
}

C4_STATES = {
    "AL": AL, "CT": CT, "DC": DC, "MN": MN, "WI": WI,
}

def add_states_to_file(filepath, extra_fields=None):
    """Add C4 states to a us_states.json file."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    for code, state in sorted(C4_STATES.items()):
        entry = copy.deepcopy(state)
        if extra_fields:
            entry.update(extra_fields)
        data["states"][code] = entry
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Written {filepath} -- {len(data['states'])} states total")

# 2025
print("Adding C4 states to 2025...")
add_states_to_file(ROOT / "data" / "tax_years" / "2025" / "us_states.json")

# 2026 (with state_parameter_year: 2025)
print("Adding C4 states to 2026...")
add_states_to_file(
    ROOT / "data" / "tax_years" / "2026" / "us_states.json",
    extra_fields={"state_parameter_year": 2025},
)

print("Done!")
