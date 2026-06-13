"""Add C3b progressive states (NM/ND/OH/OK/RI/SC/VA/VT/WV) to us_states.json."""

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

# ---------- NM: 6 brackets, single vs MFJ (HoH=MFJ) ----------
NM = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": {
        "single": [
            {"up_to": 5500, "rate": 0.015},
            {"up_to": 11000, "rate": 0.032},
            {"up_to": 16500, "rate": 0.043},
            {"up_to": 33500, "rate": 0.047},
            {"up_to": 210000, "rate": 0.049},
            {"up_to": None, "rate": 0.059},
        ],
        "married_filing_jointly": [
            {"up_to": 8000, "rate": 0.015},
            {"up_to": 16000, "rate": 0.032},
            {"up_to": 25000, "rate": 0.043},
            {"up_to": 50000, "rate": 0.047},
            {"up_to": 315000, "rate": 0.049},
            {"up_to": None, "rate": 0.059},
        ],
        "married_filing_separately": [
            {"up_to": 5500, "rate": 0.015},
            {"up_to": 11000, "rate": 0.032},
            {"up_to": 16500, "rate": 0.043},
            {"up_to": 33500, "rate": 0.047},
            {"up_to": 210000, "rate": 0.049},
            {"up_to": None, "rate": 0.059},
        ],
        "head_of_household": [
            {"up_to": 8000, "rate": 0.015},
            {"up_to": 16000, "rate": 0.032},
            {"up_to": 25000, "rate": 0.043},
            {"up_to": 50000, "rate": 0.047},
            {"up_to": 315000, "rate": 0.049},
            {"up_to": None, "rate": 0.059},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 8000, "rate": 0.015},
            {"up_to": 16000, "rate": 0.032},
            {"up_to": 25000, "rate": 0.043},
            {"up_to": 50000, "rate": 0.047},
            {"up_to": 315000, "rate": 0.049},
            {"up_to": None, "rate": 0.059},
        ],
    },
    "source_ids": ["nm_trd_income_tax_2025"],
    "notes": "NM 2025 brackets per HB 252; HoH uses MFJ schedule. Dependent deductions and low/middle-income exemption not modeled.",
}

# ---------- ND: 3 brackets (incl 0%), separate per status ----------
ND = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": {
        "single": [
            {"up_to": 48475, "rate": 0},
            {"up_to": 244825, "rate": 0.0195},
            {"up_to": None, "rate": 0.025},
        ],
        "married_filing_jointly": [
            {"up_to": 96950, "rate": 0},
            {"up_to": 489650, "rate": 0.0195},
            {"up_to": None, "rate": 0.025},
        ],
        "married_filing_separately": [
            {"up_to": 48475, "rate": 0},
            {"up_to": 244825, "rate": 0.0195},
            {"up_to": None, "rate": 0.025},
        ],
        "head_of_household": [
            {"up_to": 72713, "rate": 0},
            {"up_to": 367238, "rate": 0.0195},
            {"up_to": None, "rate": 0.025},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 96950, "rate": 0},
            {"up_to": 489650, "rate": 0.0195},
            {"up_to": None, "rate": 0.025},
        ],
    },
    "source_ids": ["nd_tax_income_tax_2025"],
    "notes": "ND 2025 per HB 1158; 0% bracket exempts first $48,475 single / $96,950 MFJ. Very low rates.",
}

# ---------- OH: 3 brackets (incl 0%), uniform, federal_agi base ----------
OH = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": same_all([
        {"up_to": 26050, "rate": 0},
        {"up_to": 100000, "rate": 0.0275},
        {"up_to": None, "rate": 0.03125},
    ]),
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 1850,
            "married_filing_jointly": 3700,
            "married_filing_separately": 1850,
            "head_of_household": 1850,
            "qualifying_surviving_spouse": 1850,
        },
    },
    "source_ids": ["oh_tax_income_tax_2025"],
    "notes": "OH 2025; no standard deduction. Personal exemption modeled at >$80k MAGI tier ($1,850/person); stepped exemption ($2,350/$2,100/$1,850 by MAGI) and joint filing credit not modeled. Uniform brackets.",
}

# ---------- OK: 6 brackets, single vs MFJ (HoH=single) ----------
OK = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": {
        "single": [
            {"up_to": 1000, "rate": 0.0025},
            {"up_to": 2500, "rate": 0.0075},
            {"up_to": 3750, "rate": 0.0175},
            {"up_to": 4900, "rate": 0.0275},
            {"up_to": 7200, "rate": 0.0375},
            {"up_to": None, "rate": 0.0475},
        ],
        "married_filing_jointly": [
            {"up_to": 2000, "rate": 0.0025},
            {"up_to": 5000, "rate": 0.0075},
            {"up_to": 7500, "rate": 0.0175},
            {"up_to": 9800, "rate": 0.0275},
            {"up_to": 12200, "rate": 0.0375},
            {"up_to": None, "rate": 0.0475},
        ],
        "married_filing_separately": [
            {"up_to": 1000, "rate": 0.0025},
            {"up_to": 2500, "rate": 0.0075},
            {"up_to": 3750, "rate": 0.0175},
            {"up_to": 4900, "rate": 0.0275},
            {"up_to": 7200, "rate": 0.0375},
            {"up_to": None, "rate": 0.0475},
        ],
        "head_of_household": [
            {"up_to": 1000, "rate": 0.0025},
            {"up_to": 2500, "rate": 0.0075},
            {"up_to": 3750, "rate": 0.0175},
            {"up_to": 4900, "rate": 0.0275},
            {"up_to": 7200, "rate": 0.0375},
            {"up_to": None, "rate": 0.0475},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 2000, "rate": 0.0025},
            {"up_to": 5000, "rate": 0.0075},
            {"up_to": 7500, "rate": 0.0175},
            {"up_to": 9800, "rate": 0.0275},
            {"up_to": 12200, "rate": 0.0375},
            {"up_to": None, "rate": 0.0475},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 7350,
            "married_filing_jointly": 14700,
            "married_filing_separately": 7350,
            "head_of_household": 10350,
            "qualifying_surviving_spouse": 13700,
        },
    },
    "source_ids": ["ok_tax_income_tax_2025"],
    "notes": "OK 2025; brackets not indexed for inflation. Standard deduction ($6,350/$12,700/$9,350) + personal exemption ($1,000/person) combined. HoH uses single brackets.",
}

# ---------- RI: 3 brackets, uniform, federal_agi base ----------
RI = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": same_all([
        {"up_to": 79900, "rate": 0.0375},
        {"up_to": 181650, "rate": 0.0475},
        {"up_to": None, "rate": 0.0599},
    ]),
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 16000,
            "married_filing_jointly": 32000,
            "married_filing_separately": 16000,
            "head_of_household": 21450,
            "qualifying_surviving_spouse": 26900,
        },
    },
    "source_ids": ["ri_dor_income_tax_2025"],
    "notes": "RI 2025; uniform brackets. Standard deduction ($10,900/$21,800/$16,350) + personal exemption ($5,100/person) combined; phaseout above $254,250 MAGI not modeled.",
}

# ---------- SC: 3 brackets (incl 0%), uniform, federal_taxable_income ----------
SC = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": same_all([
        {"up_to": 3560, "rate": 0},
        {"up_to": 17830, "rate": 0.03},
        {"up_to": None, "rate": 0.06},
    ]),
    "source_ids": ["sc_dor_income_tax_2025"],
    "notes": "SC 2025; uniform brackets, 0% on first $3,560. Uses federal taxable income. Dependent exemption ($4,930/dependent) not modeled. Major reform in 2026 (H.4216).",
}

# ---------- VA: 4 brackets, uniform, federal_agi base ----------
VA = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": same_all([
        {"up_to": 3000, "rate": 0.02},
        {"up_to": 5000, "rate": 0.03},
        {"up_to": 17000, "rate": 0.05},
        {"up_to": None, "rate": 0.0575},
    ]),
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 9680,
            "married_filing_jointly": 19360,
            "married_filing_separately": 9680,
            "head_of_household": 9680,
            "qualifying_surviving_spouse": 18430,
        },
    },
    "source_ids": ["va_tax_income_tax_2025"],
    "notes": "VA 2025; uniform brackets with very low thresholds. Standard deduction ($8,750/$17,500) + personal exemption ($930/person) combined; standard deduction phaseout above $50k single / $75k MFJ NOT modeled—overstates deduction for high earners.",
}

# ---------- VT: 4 brackets, per-status, federal_agi base ----------
VT = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": {
        "single": [
            {"up_to": 47900, "rate": 0.0335},
            {"up_to": 116350, "rate": 0.066},
            {"up_to": 242000, "rate": 0.076},
            {"up_to": None, "rate": 0.0875},
        ],
        "married_filing_jointly": [
            {"up_to": 79950, "rate": 0.0335},
            {"up_to": 193350, "rate": 0.066},
            {"up_to": 294650, "rate": 0.076},
            {"up_to": None, "rate": 0.0875},
        ],
        "married_filing_separately": [
            {"up_to": 47900, "rate": 0.0335},
            {"up_to": 116350, "rate": 0.066},
            {"up_to": 242000, "rate": 0.076},
            {"up_to": None, "rate": 0.0875},
        ],
        "head_of_household": [
            {"up_to": 64000, "rate": 0.0335},
            {"up_to": 153800, "rate": 0.066},
            {"up_to": 240800, "rate": 0.076},
            {"up_to": None, "rate": 0.0875},
        ],
        "qualifying_surviving_spouse": [
            {"up_to": 79950, "rate": 0.0335},
            {"up_to": 193350, "rate": 0.066},
            {"up_to": 294650, "rate": 0.076},
            {"up_to": None, "rate": 0.0875},
        ],
    },
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 12950,
            "married_filing_jointly": 25900,
            "married_filing_separately": 12950,
            "head_of_household": 16750,
            "qualifying_surviving_spouse": 20600,
        },
    },
    "source_ids": ["vt_tax_income_tax_2025"],
    "notes": "VT 2025; indexed brackets. Standard deduction ($7,650/$15,300/$11,450) + personal exemption ($5,300/person) combined into standard_deduction.",
}

# ---------- WV: 5 brackets, uniform, federal_agi base ----------
WV = {
    "income_tax_type": "progressive",
    "status": "effective",
    "brackets": same_all([
        {"up_to": 10000, "rate": 0.0222},
        {"up_to": 25000, "rate": 0.0296},
        {"up_to": 40000, "rate": 0.0333},
        {"up_to": 60000, "rate": 0.0444},
        {"up_to": None, "rate": 0.0482},
    ]),
    "tax_base": {
        "start_from": "federal_agi",
        "allows_qbi": False,
        "standard_deduction": {
            "single": 2000,
            "married_filing_jointly": 4000,
            "married_filing_separately": 2000,
            "head_of_household": 2000,
            "qualifying_surviving_spouse": 2000,
        },
    },
    "source_ids": ["wv_tax_income_tax_2025"],
    "notes": "WV 2025 per SB 2033; uniform brackets. No standard deduction; personal exemption ($2,000/person) modeled as standard_deduction.",
}

C3B_STATES = {
    "NM": NM, "ND": ND, "OH": OH, "OK": OK, "RI": RI,
    "SC": SC, "VA": VA, "VT": VT, "WV": WV,
}

def add_states_to_file(filepath, extra_fields=None):
    """Add C3b states to a us_states.json file."""
    with open(filepath) as f:
        data = json.load(f)
    for code, state in sorted(C3B_STATES.items()):
        entry = copy.deepcopy(state)
        if extra_fields:
            entry.update(extra_fields)
        data["states"][code] = entry
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Written {filepath} — {len(data['states'])} states total")

# 2025
print("Adding C3b states to 2025...")
add_states_to_file(ROOT / "data" / "tax_years" / "2025" / "us_states.json")

# 2026 (with state_parameter_year: 2025)
print("Adding C3b states to 2026...")
add_states_to_file(
    ROOT / "data" / "tax_years" / "2026" / "us_states.json",
    extra_fields={"state_parameter_year": 2025},
)

print("Done!")
