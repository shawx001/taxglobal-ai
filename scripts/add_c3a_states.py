"""Add C3a progressive states to 2025 us_states.json."""
import json
import copy
import sys

def main():
    with open("data/tax_years/2025/us_states.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # Helper: same brackets for all filing statuses
    def same_all(brackets):
        return {
            "single": brackets,
            "married_filing_separately": brackets,
            "married_filing_jointly": brackets,
            "head_of_household": brackets,
            "qualifying_surviving_spouse": brackets,
        }

    # 1. ARKANSAS (AR) - 5 brackets (incl 0%), same for all
    ar_brackets = [
        {"up_to": 5099, "rate": 0},
        {"up_to": 10299, "rate": 0.02},
        {"up_to": 14699, "rate": 0.03},
        {"up_to": 24299, "rate": 0.034},
        {"up_to": None, "rate": 0.039},
    ]
    data["states"]["AR"] = {
        "name": "Arkansas",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["ar_dfa_income_tax_2025"],
        "citation": "Arkansas Department of Finance and Administration 2025 Form AR1000F instructions list Arkansas individual income tax rate schedules.",
        "notes": "Act 1 of the 2024 Second Extraordinary Session reduced top rate from 4.4% to 3.9% effective 2025. Brackets indexed annually. $29 personal tax credit per filer/dependent not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 2410,
                "married_filing_separately": 2410,
                "married_filing_jointly": 4820,
                "head_of_household": 2410,
                "qualifying_surviving_spouse": 4820,
            },
            "source_ids": ["ar_dfa_income_tax_2025"],
            "citation": "Arkansas 2025 standard deduction is $2,410 (single/MFS/HOH) or $4,820 (MFJ/QSS).",
            "notes": "Arkansas-specific modifications to federal AGI, itemized deduction option, and $29 personal tax credit are not modeled.",
        },
        "brackets": same_all(ar_brackets),
    }

    # 2. DELAWARE (DE) - 7 brackets (incl 0%), same for all
    de_brackets = [
        {"up_to": 2000, "rate": 0},
        {"up_to": 5000, "rate": 0.022},
        {"up_to": 10000, "rate": 0.039},
        {"up_to": 20000, "rate": 0.048},
        {"up_to": 25000, "rate": 0.052},
        {"up_to": 60000, "rate": 0.0555},
        {"up_to": None, "rate": 0.066},
    ]
    data["states"]["DE"] = {
        "name": "Delaware",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["de_dor_income_tax_2025"],
        "citation": "Delaware Division of Revenue 2025 personal income tax forms and instructions list the Delaware tax rate schedule.",
        "notes": "Delaware personal exemption credit ($110 per exemption, enhanced $330 for income $18,000-$36,000) not modeled. Delaware-specific modifications and itemized deductions not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 3250,
                "married_filing_separately": 3250,
                "married_filing_jointly": 6500,
                "head_of_household": 3250,
                "qualifying_surviving_spouse": 6500,
            },
            "source_ids": ["de_dor_income_tax_2025"],
            "citation": "Delaware 2025 standard deduction is $3,250 (single/MFS/HOH) or $6,500 (MFJ/QSS).",
            "notes": "Additional $2,500 deduction for age 65+/blind not modeled. Personal exemption credit ($110/exemption) not modeled.",
        },
        "brackets": same_all(de_brackets),
    }

    # 3. HAWAII (HI) - 12 brackets, filing-status-specific
    data["states"]["HI"] = {
        "name": "Hawaii",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["hi_dotax_income_tax_2025"],
        "citation": "Hawaii Department of Taxation 2025 individual income tax rate schedules list Hawaii tax brackets by filing status per Act 46, SLH 2024.",
        "notes": "Act 46 (2024) widened bracket thresholds effective 2025. Personal exemption ($1,144) combined into standard deduction. Hawaii modifications to federal AGI, credits, and refundable food/excise tax credit not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 5544,
                "married_filing_separately": 5544,
                "married_filing_jointly": 11088,
                "head_of_household": 7568,
                "qualifying_surviving_spouse": 9944,
            },
            "source_ids": ["hi_dotax_income_tax_2025"],
            "citation": "Hawaii 2025 standard deduction ($4,400 S/$8,800 MFJ/$6,424 HOH) plus personal exemption ($1,144 per person) combined.",
            "notes": "Combined standard deduction + personal exemption for primary filer(s). Dependent exemptions ($1,144 each) not included. QSS uses MFJ standard deduction + one personal exemption.",
        },
        "brackets": {
            "single": [
                {"up_to": 9600, "rate": 0.014},
                {"up_to": 14400, "rate": 0.032},
                {"up_to": 19200, "rate": 0.055},
                {"up_to": 24000, "rate": 0.064},
                {"up_to": 36000, "rate": 0.068},
                {"up_to": 48000, "rate": 0.072},
                {"up_to": 125000, "rate": 0.076},
                {"up_to": 175000, "rate": 0.079},
                {"up_to": 225000, "rate": 0.0825},
                {"up_to": 275000, "rate": 0.09},
                {"up_to": 325000, "rate": 0.10},
                {"up_to": None, "rate": 0.11},
            ],
            "married_filing_separately": [
                {"up_to": 9600, "rate": 0.014},
                {"up_to": 14400, "rate": 0.032},
                {"up_to": 19200, "rate": 0.055},
                {"up_to": 24000, "rate": 0.064},
                {"up_to": 36000, "rate": 0.068},
                {"up_to": 48000, "rate": 0.072},
                {"up_to": 125000, "rate": 0.076},
                {"up_to": 175000, "rate": 0.079},
                {"up_to": 225000, "rate": 0.0825},
                {"up_to": 275000, "rate": 0.09},
                {"up_to": 325000, "rate": 0.10},
                {"up_to": None, "rate": 0.11},
            ],
            "married_filing_jointly": [
                {"up_to": 19200, "rate": 0.014},
                {"up_to": 28800, "rate": 0.032},
                {"up_to": 38400, "rate": 0.055},
                {"up_to": 48000, "rate": 0.064},
                {"up_to": 72000, "rate": 0.068},
                {"up_to": 96000, "rate": 0.072},
                {"up_to": 250000, "rate": 0.076},
                {"up_to": 350000, "rate": 0.079},
                {"up_to": 450000, "rate": 0.0825},
                {"up_to": 550000, "rate": 0.09},
                {"up_to": 650000, "rate": 0.10},
                {"up_to": None, "rate": 0.11},
            ],
            "head_of_household": [
                {"up_to": 14400, "rate": 0.014},
                {"up_to": 21600, "rate": 0.032},
                {"up_to": 28800, "rate": 0.055},
                {"up_to": 36000, "rate": 0.064},
                {"up_to": 54000, "rate": 0.068},
                {"up_to": 72000, "rate": 0.072},
                {"up_to": 187500, "rate": 0.076},
                {"up_to": 262500, "rate": 0.079},
                {"up_to": 337500, "rate": 0.0825},
                {"up_to": 412500, "rate": 0.09},
                {"up_to": 487500, "rate": 0.10},
                {"up_to": None, "rate": 0.11},
            ],
            "qualifying_surviving_spouse": [
                {"up_to": 19200, "rate": 0.014},
                {"up_to": 28800, "rate": 0.032},
                {"up_to": 38400, "rate": 0.055},
                {"up_to": 48000, "rate": 0.064},
                {"up_to": 72000, "rate": 0.068},
                {"up_to": 96000, "rate": 0.072},
                {"up_to": 250000, "rate": 0.076},
                {"up_to": 350000, "rate": 0.079},
                {"up_to": 450000, "rate": 0.0825},
                {"up_to": 550000, "rate": 0.09},
                {"up_to": 650000, "rate": 0.10},
                {"up_to": None, "rate": 0.11},
            ],
        },
    }

    # 4. KANSAS (KS) - 2 brackets, filing-status-specific thresholds
    data["states"]["KS"] = {
        "name": "Kansas",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["ks_dor_income_tax_2025"],
        "citation": "Kansas Department of Revenue 2025 income tax booklet lists Kansas tax rate schedules and deduction amounts per Senate Bill 1.",
        "notes": "SB 1 consolidated three brackets into two and reduced rates effective 2025. Personal exemption ($9,160 per filer) combined into standard deduction. Dependent exemptions ($2,320 each) not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 12765,
                "married_filing_separately": 13280,
                "married_filing_jointly": 26560,
                "head_of_household": 15340,
                "qualifying_surviving_spouse": 26560,
            },
            "source_ids": ["ks_dor_income_tax_2025"],
            "citation": "Kansas 2025 standard deduction ($3,605 S/$8,240 MFJ/$4,120 MFS/$6,180 HOH) plus personal exemption ($9,160 per filer, $18,320 MFJ) combined.",
            "notes": "Combined standard deduction + personal exemption for primary filer(s). Dependent exemptions ($2,320 each) not included. Kansas-specific Schedule S modifications not modeled.",
        },
        "brackets": {
            "single": [
                {"up_to": 23000, "rate": 0.052},
                {"up_to": None, "rate": 0.0558},
            ],
            "married_filing_separately": [
                {"up_to": 23000, "rate": 0.052},
                {"up_to": None, "rate": 0.0558},
            ],
            "married_filing_jointly": [
                {"up_to": 46000, "rate": 0.052},
                {"up_to": None, "rate": 0.0558},
            ],
            "head_of_household": [
                {"up_to": 23000, "rate": 0.052},
                {"up_to": None, "rate": 0.0558},
            ],
            "qualifying_surviving_spouse": [
                {"up_to": 46000, "rate": 0.052},
                {"up_to": None, "rate": 0.0558},
            ],
        },
    }

    # 5. MAINE (ME) - 3 brackets, filing-status-specific thresholds
    data["states"]["ME"] = {
        "name": "Maine",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["me_rs_income_tax_2025"],
        "citation": "Maine Revenue Services 2025 individual income tax rate schedule lists marginal brackets by filing status.",
        "notes": "Personal exemption ($5,150) combined into standard deduction. Standard deduction and personal exemption phase out at high income (not modeled). Dependent exemptions not included. Maine-specific modifications, credits, and property tax fairness credit not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 20150,
                "married_filing_separately": 20150,
                "married_filing_jointly": 40300,
                "head_of_household": 27650,
                "qualifying_surviving_spouse": 35150,
            },
            "source_ids": ["me_rs_income_tax_2025"],
            "citation": "Maine 2025 standard deduction ($15,000 S/MFS, $30,000 MFJ, $22,500 HOH) plus personal exemption ($5,150 per person) combined.",
            "notes": "Combined standard deduction + personal exemption for primary filer(s). Phaseout above $100,000 (S) / $200,000 (MFJ) not modeled. Dependent exemptions not included.",
        },
        "brackets": {
            "single": [
                {"up_to": 26800, "rate": 0.058},
                {"up_to": 63450, "rate": 0.0675},
                {"up_to": None, "rate": 0.0715},
            ],
            "married_filing_separately": [
                {"up_to": 26800, "rate": 0.058},
                {"up_to": 63450, "rate": 0.0675},
                {"up_to": None, "rate": 0.0715},
            ],
            "married_filing_jointly": [
                {"up_to": 53600, "rate": 0.058},
                {"up_to": 126900, "rate": 0.0675},
                {"up_to": None, "rate": 0.0715},
            ],
            "head_of_household": [
                {"up_to": 40200, "rate": 0.058},
                {"up_to": 95150, "rate": 0.0675},
                {"up_to": None, "rate": 0.0715},
            ],
            "qualifying_surviving_spouse": [
                {"up_to": 53600, "rate": 0.058},
                {"up_to": 126900, "rate": 0.0675},
                {"up_to": None, "rate": 0.0715},
            ],
        },
    }

    # 6. MARYLAND (MD) - 10 brackets, filing-status-specific
    md_single = [
        {"up_to": 1000, "rate": 0.02},
        {"up_to": 2000, "rate": 0.03},
        {"up_to": 3000, "rate": 0.04},
        {"up_to": 100000, "rate": 0.0475},
        {"up_to": 125000, "rate": 0.05},
        {"up_to": 150000, "rate": 0.0525},
        {"up_to": 250000, "rate": 0.055},
        {"up_to": 500000, "rate": 0.0575},
        {"up_to": 1000000, "rate": 0.0625},
        {"up_to": None, "rate": 0.065},
    ]
    md_joint = [
        {"up_to": 1000, "rate": 0.02},
        {"up_to": 2000, "rate": 0.03},
        {"up_to": 3000, "rate": 0.04},
        {"up_to": 150000, "rate": 0.0475},
        {"up_to": 175000, "rate": 0.05},
        {"up_to": 225000, "rate": 0.0525},
        {"up_to": 300000, "rate": 0.055},
        {"up_to": 600000, "rate": 0.0575},
        {"up_to": 1200000, "rate": 0.0625},
        {"up_to": None, "rate": 0.065},
    ]
    data["states"]["MD"] = {
        "name": "Maryland",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["md_comptroller_income_tax_2025"],
        "citation": "Maryland Comptroller 2025 tax alert lists new state income tax brackets and deduction changes effective for tax years beginning after 12/31/2024.",
        "notes": "Two new high-income brackets (6.25% and 6.50%) added for 2025. Personal exemption ($3,200) combined into standard deduction. County income tax (2.25%-3.3%), 2% capital gains surtax above $350K FAGI, and itemized deduction phaseout not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 6550,
                "married_filing_separately": 6550,
                "married_filing_jointly": 13100,
                "head_of_household": 9900,
                "qualifying_surviving_spouse": 9900,
            },
            "source_ids": ["md_comptroller_income_tax_2025"],
            "citation": "Maryland 2025 standard deduction ($3,350 S/MFS, $6,700 MFJ/HOH/QSS) plus personal exemption ($3,200 per person) combined.",
            "notes": "Combined standard deduction + personal exemption for primary filer(s). Dependent exemptions ($3,200 each) not included. County income tax adds 2.25%-3.3% and is not modeled.",
        },
        "brackets": {
            "single": md_single,
            "married_filing_separately": md_single,
            "married_filing_jointly": md_joint,
            "head_of_household": md_joint,
            "qualifying_surviving_spouse": md_joint,
        },
    }

    # 7. MISSOURI (MO) - 8 brackets (incl 0%), same for all, federal std deduction
    mo_brackets = [
        {"up_to": 1313, "rate": 0},
        {"up_to": 2626, "rate": 0.02},
        {"up_to": 3939, "rate": 0.025},
        {"up_to": 5252, "rate": 0.03},
        {"up_to": 6565, "rate": 0.035},
        {"up_to": 7878, "rate": 0.04},
        {"up_to": 9191, "rate": 0.045},
        {"up_to": None, "rate": 0.047},
    ]
    data["states"]["MO"] = {
        "name": "Missouri",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["mo_dor_income_tax_2025"],
        "citation": "Missouri Department of Revenue 2025 tax year changes list Missouri individual income tax brackets indexed for inflation.",
        "notes": "Missouri conforms to federal standard deduction. Brackets include a $0-$1,313 zero bracket. Personal exemptions were eliminated. Missouri-specific modifications not modeled.",
        "brackets": same_all(mo_brackets),
    }

    # 8. MONTANA (MT) - 2 brackets, filing-status-specific
    data["states"]["MT"] = {
        "name": "Montana",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["mt_dor_income_tax_2025"],
        "citation": "Montana Department of Revenue 2025 tax rates and deductions list Montana individual income tax brackets per SB 121 (2023).",
        "notes": "Montana starts from federal taxable income (federal standard deduction already included). SB 121 (2023) established two-bracket system, reduced top rate from 6.5% to 5.9% effective TY 2024. Brackets indexed annually. Montana-specific additions/subtractions not modeled.",
        "brackets": {
            "single": [
                {"up_to": 21100, "rate": 0.047},
                {"up_to": None, "rate": 0.059},
            ],
            "married_filing_separately": [
                {"up_to": 21100, "rate": 0.047},
                {"up_to": None, "rate": 0.059},
            ],
            "married_filing_jointly": [
                {"up_to": 42200, "rate": 0.047},
                {"up_to": None, "rate": 0.059},
            ],
            "head_of_household": [
                {"up_to": 30750, "rate": 0.047},
                {"up_to": None, "rate": 0.059},
            ],
            "qualifying_surviving_spouse": [
                {"up_to": 42200, "rate": 0.047},
                {"up_to": None, "rate": 0.059},
            ],
        },
    }

    # 9. NEBRASKA (NE) - 4 brackets, filing-status-specific
    data["states"]["NE"] = {
        "name": "Nebraska",
        "income_tax_type": "progressive",
        "status": "effective",
        "effective_date": "2025-01-01",
        "source_ids": ["ne_dor_income_tax_2025"],
        "citation": "Nebraska Department of Revenue 2025 individual income tax booklet lists Nebraska tax rate schedules and standard deduction amounts per LB 754 (2023) phased reduction.",
        "notes": "LB 754 (2023) phased rate reduction; 2025 top rate 5.20% (from 5.84%). Brackets indexed annually. Personal exemption credit ($171/exemption) not modeled. Nebraska-specific modifications and credits not modeled.",
        "tax_base": {
            "start_from": "federal_agi",
            "allows_qbi": False,
            "standard_deduction": {
                "single": 8600,
                "married_filing_separately": 8600,
                "married_filing_jointly": 17200,
                "head_of_household": 12600,
                "qualifying_surviving_spouse": 17200,
            },
            "source_ids": ["ne_dor_income_tax_2025"],
            "citation": "Nebraska 2025 standard deduction is $8,600 (single/MFS), $17,200 (MFJ/QSS), $12,600 (HOH).",
            "notes": "Personal exemption credit ($171 per exemption) is a non-refundable credit against tax, not a deduction. Not modeled.",
        },
        "brackets": {
            "single": [
                {"up_to": 4030, "rate": 0.0246},
                {"up_to": 24120, "rate": 0.0351},
                {"up_to": 38870, "rate": 0.0501},
                {"up_to": None, "rate": 0.052},
            ],
            "married_filing_separately": [
                {"up_to": 4030, "rate": 0.0246},
                {"up_to": 24120, "rate": 0.0351},
                {"up_to": 38870, "rate": 0.0501},
                {"up_to": None, "rate": 0.052},
            ],
            "married_filing_jointly": [
                {"up_to": 8040, "rate": 0.0246},
                {"up_to": 48250, "rate": 0.0351},
                {"up_to": 77730, "rate": 0.0501},
                {"up_to": None, "rate": 0.052},
            ],
            "head_of_household": [
                {"up_to": 7510, "rate": 0.0246},
                {"up_to": 38590, "rate": 0.0351},
                {"up_to": 57630, "rate": 0.0501},
                {"up_to": None, "rate": 0.052},
            ],
            "qualifying_surviving_spouse": [
                {"up_to": 8040, "rate": 0.0246},
                {"up_to": 48250, "rate": 0.0351},
                {"up_to": 77730, "rate": 0.0501},
                {"up_to": None, "rate": 0.052},
            ],
        },
    }

    with open("data/tax_years/2025/us_states.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Total states in 2025: {len(data['states'])}")
    c3a = ["AR", "DE", "HI", "KS", "ME", "MD", "MO", "MT", "NE"]
    for s in c3a:
        st = data["states"][s]
        brackets = st["brackets"]["single"]
        print(f"{s}: {st['income_tax_type']}, {len(brackets)} brackets, top rate {brackets[-1]['rate']}")


if __name__ == "__main__":
    main()
