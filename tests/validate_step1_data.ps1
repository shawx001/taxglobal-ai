$ErrorActionPreference = "Stop"

function Read-Json($Path) {
  if (!(Test-Path -LiteralPath $Path)) {
    throw "Missing JSON file: $Path"
  }
  return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

$sourceIds = @{}

function Add-ManifestSources($ManifestPath) {
  $manifest = Read-Json $ManifestPath
  if (!$manifest.sources -or $manifest.sources.Count -lt 1) {
    throw "$ManifestPath must contain at least one source"
  }

  foreach ($source in $manifest.sources) {
    if (!$source.source_id) { throw "Source missing source_id in $ManifestPath" }
    $status = if ($source.status) { $source.status } else { "archived" }
    if ($status -in @("archived", "archived_redacted")) {
      if (!$source.local_path) { throw "Source $($source.source_id) missing local_path" }
      if (!$source.content_hash) { throw "Source $($source.source_id) missing content_hash" }
      if (!(Test-Path -LiteralPath $source.local_path)) {
        throw "Archived source file missing: $($source.local_path)"
      }
      $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.local_path).Hash
      if ($actualHash -ne $source.content_hash) {
        throw "Hash mismatch for $($source.source_id): expected $($source.content_hash), got $actualHash"
      }
    } else {
      if (($source.PSObject.Properties.Name -contains "local_path") -and $source.local_path) {
        throw "Non-archived source $($source.source_id) must not claim local_path"
      }
      if (($source.PSObject.Properties.Name -contains "content_hash") -and $source.content_hash) {
        throw "Non-archived source $($source.source_id) must not claim content_hash"
      }
      if (!$source.notes) {
        throw "Non-archived source $($source.source_id) must include notes"
      }
    }
    $sourceIds[$source.source_id] = $true
  }
}

Add-ManifestSources "data/sources/us/2025/source_manifest.json"
Add-ManifestSources "data/sources/us/2026/source_manifest.json"

$ruleFiles = @(
  "data/tax_years/2025/us_federal.json",
  "data/tax_years/2025/us_fica.json",
  "data/tax_years/2025/us_feie.json",
  "data/tax_years/2025/us_states.json",
  "data/tax_years/2025/us_nexus.json",
  "data/tax_years/2025/us_capital_gains.json",
  "data/tax_years/2025/us_qbi.json"
)

foreach ($file in $ruleFiles) {
  $doc = Read-Json $file
  if (!$doc.schema_version) { throw "$file missing schema_version" }
  if ($doc.tax_year -ne 2025) { throw "$file tax_year must be 2025" }
  if ($doc.status -eq "effective" -and !$doc.effective_date) {
    throw "$file effective rule file missing effective_date"
  }
}

$ruleFiles2026 = @(
  "data/tax_years/2026/us_federal.json",
  "data/tax_years/2026/us_fica.json",
  "data/tax_years/2026/us_feie.json",
  "data/tax_years/2026/us_states.json",
  "data/tax_years/2026/us_nexus.json",
  "data/tax_years/2026/us_capital_gains.json",
  "data/tax_years/2026/us_qbi.json"
)

foreach ($file in $ruleFiles2026) {
  $doc = Read-Json $file
  if (!$doc.schema_version) { throw "$file missing schema_version" }
  if ($doc.tax_year -ne 2026) { throw "$file tax_year must be 2026" }
  if ($doc.status -eq "effective" -and !$doc.effective_date) {
    throw "$file effective rule file missing effective_date"
  }
}

function Assert-SourceIdsExist($Node, $Path) {
  if ($null -eq $Node) { return }
  if ($Node -is [System.Array]) {
    for ($i = 0; $i -lt $Node.Count; $i++) {
      Assert-SourceIdsExist $Node[$i] "$Path[$i]"
    }
    return
  }
  if ($Node -is [pscustomobject]) {
    if ($Node.PSObject.Properties.Name -contains "sources") {
      throw "$Path uses deprecated key 'sources'; use source_ids"
    }
    if ($Node.PSObject.Properties.Name -contains "source_ids") {
      foreach ($sourceId in $Node.source_ids) {
        if (!$sourceIds.ContainsKey($sourceId)) {
          throw "$Path references unknown source_id $sourceId"
        }
      }
    }
    foreach ($prop in $Node.PSObject.Properties) {
      Assert-SourceIdsExist $prop.Value "$Path.$($prop.Name)"
    }
  }
}

foreach ($file in $ruleFiles) {
  $doc = Read-Json $file
  Assert-SourceIdsExist $doc $file
}

foreach ($file in $ruleFiles2026) {
  $doc = Read-Json $file
  Assert-SourceIdsExist $doc $file
}

$federal = Read-Json "data/tax_years/2025/us_federal.json"
if ($federal.standard_deduction.single -ne 15000) {
  throw "Unexpected 2025 single standard deduction"
}
if ($federal.ordinary_income_brackets.single[0].up_to -ne 11925) {
  throw "Unexpected first 2025 single federal bracket cap"
}

$fica = Read-Json "data/tax_years/2025/us_fica.json"
if ($fica.social_security.wage_base -ne 176100) {
  throw "Unexpected 2025 Social Security wage base"
}
if ($fica.additional_medicare.taxpayer_thresholds.married_filing_jointly -ne 250000) {
  throw "Unexpected Additional Medicare MFJ threshold"
}

$feie = Read-Json "data/tax_years/2025/us_feie.json"
if ($feie.foreign_earned_income_exclusion.maximum_exclusion -ne 130000) {
  throw "Unexpected 2025 FEIE maximum exclusion"
}

$qbi = Read-Json "data/tax_years/2025/us_qbi.json"
$requiredQbiFilingStatuses = @(
  "single",
  "married_filing_jointly",
  "qualifying_surviving_spouse",
  "head_of_household",
  "married_filing_separately"
)
$expectedQbiPhaseInWindows = @{
  single = 50000
  head_of_household = 50000
  married_filing_separately = 25000
  qualifying_surviving_spouse = 50000
  married_filing_jointly = 100000
}
if (!$qbi.qbi_deduction) { throw "QBI file missing qbi_deduction" }
if ($qbi.qbi_deduction.rate -ne 0.2) { throw "Unexpected QBI deduction rate" }
if (!$qbi.qbi_deduction.effective_date) { throw "qbi_deduction missing effective_date" }
if (!$qbi.qbi_deduction.citation) { throw "qbi_deduction missing citation" }
if (!$qbi.qbi_deduction.wage_ubia_limit) { throw "qbi_deduction missing wage_ubia_limit" }
if ($qbi.qbi_deduction.wage_ubia_limit.half_w2_wages_rate -ne 0.5) {
  throw "Unexpected QBI half_w2_wages_rate"
}
if ($qbi.qbi_deduction.wage_ubia_limit.quarter_w2_wages_rate -ne 0.25) {
  throw "Unexpected QBI quarter_w2_wages_rate"
}
if ($qbi.qbi_deduction.wage_ubia_limit.ubia_rate -ne 0.025) {
  throw "Unexpected QBI ubia_rate"
}
if (!$qbi.source_ids -or $qbi.source_ids.Count -lt 1) {
  throw "QBI file missing source_ids"
}
if (!$qbi.qbi_deduction.source_ids -or $qbi.qbi_deduction.source_ids.Count -lt 1) {
  throw "qbi_deduction missing source_ids"
}
foreach ($filingStatus in $requiredQbiFilingStatuses) {
  foreach ($nodeName in @("taxable_income_threshold", "phase_in_window", "upper_limit")) {
    if (!($qbi.qbi_deduction.$nodeName.PSObject.Properties.Name -contains $filingStatus)) {
      throw "QBI $nodeName missing filing status $filingStatus"
    }
  }
  $threshold = $qbi.qbi_deduction.taxable_income_threshold.$filingStatus
  $window = $qbi.qbi_deduction.phase_in_window.$filingStatus
  $upperLimit = $qbi.qbi_deduction.upper_limit.$filingStatus
  if ($window -ne $expectedQbiPhaseInWindows[$filingStatus]) {
    throw "Unexpected QBI phase_in_window for $filingStatus"
  }
  if ($upperLimit -ne ($threshold + $window)) {
    throw "QBI upper_limit for $filingStatus must equal threshold + phase_in_window"
  }
}
if ($qbi.qbi_deduction.taxable_income_threshold.single -ne 197300) {
  throw "Unexpected QBI single threshold"
}
if ($qbi.qbi_deduction.taxable_income_threshold.married_filing_jointly -ne 394600) {
  throw "Unexpected QBI MFJ threshold"
}
if ($qbi.qbi_deduction.taxable_income_threshold.married_filing_separately -ne 197300) {
  throw "Unexpected QBI MFS threshold"
}
if ($qbi.qbi_deduction.taxable_income_threshold.head_of_household -ne 197300) {
  throw "Unexpected QBI HOH threshold"
}
if ($qbi.qbi_deduction.taxable_income_threshold.qualifying_surviving_spouse -ne 197300) {
  throw "Unexpected QBI QSS threshold"
}

$knowledge = Read-Json "data/knowledge/us/2025/us_core_knowledge.json"
foreach ($item in $knowledge.items) {
  if (!$item.knowledge_id) { throw "Knowledge item missing knowledge_id" }
  if (!$item.jurisdiction) { throw "Knowledge item $($item.knowledge_id) missing jurisdiction" }
  if ($item.status -eq "effective" -and !$item.effective_date) {
    throw "Knowledge item $($item.knowledge_id) missing effective_date"
  }
  foreach ($sourceId in $item.source_ids) {
    if (!$sourceIds.ContainsKey($sourceId)) {
      throw "Knowledge item $($item.knowledge_id) references unknown source_id $sourceId"
    }
  }
}

$states = Read-Json "data/tax_years/2025/us_states.json"
$requiredStateFilingStatuses = @(
  "single",
  "married_filing_jointly",
  "qualifying_surviving_spouse",
  "head_of_household",
  "married_filing_separately"
)
function Convert-RuleDecimal($Value, $Path) {
  if ($null -eq $Value) {
    throw "$Path is null"
  }
  try {
    return [decimal]::Parse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture)
  } catch {
    throw "$Path must be parseable as Decimal"
  }
}

function Assert-FederalTaxSubtractionShape($TaxBase, $Path) {
  if (!($TaxBase.PSObject.Properties.Name -contains "federal_tax_subtraction")) {
    return
  }
  $fts = $TaxBase.federal_tax_subtraction
  if (!$fts.phaseout_table) {
    throw "$Path federal_tax_subtraction missing phaseout_table"
  }
  foreach ($filingStatus in $requiredStateFilingStatuses) {
    if (!($fts.phaseout_table.PSObject.Properties.Name -contains $filingStatus)) {
      throw "$Path federal_tax_subtraction phaseout_table missing filing status $filingStatus"
    }
    $steps = @($fts.phaseout_table.$filingStatus)
    if ($steps.Count -lt 2) {
      throw "$Path federal_tax_subtraction phaseout_table.$filingStatus must have at least two steps"
    }
    $previousAgi = [decimal]-1
    for ($i = 0; $i -lt $steps.Count; $i++) {
      $step = $steps[$i]
      $limit = Convert-RuleDecimal $step.limit "$Path federal_tax_subtraction phaseout_table.$filingStatus[$i].limit"
      if ($limit -lt 0) {
        throw "$Path federal_tax_subtraction phaseout_table.$filingStatus[$i].limit must be non-negative"
      }
      if ($null -eq $step.agi_up_to) {
        if ($i -ne ($steps.Count - 1)) {
          throw "$Path federal_tax_subtraction phaseout_table.$filingStatus null agi_up_to must be last"
        }
      } else {
        $agi = Convert-RuleDecimal $step.agi_up_to "$Path federal_tax_subtraction phaseout_table.$filingStatus[$i].agi_up_to"
        if ($agi -le $previousAgi) {
          throw "$Path federal_tax_subtraction phaseout_table.$filingStatus must be sorted ascending"
        }
        $previousAgi = $agi
      }
    }
    if ($null -ne $steps[$steps.Count - 1].agi_up_to) {
      throw "$Path federal_tax_subtraction phaseout_table.$filingStatus final step must have agi_up_to null"
    }
  }
}
$allowedStateTaxBaseStarts = @("federal_agi", "federal_taxable_income", "gross_income", "state_specific")
foreach ($stateProp in $states.states.PSObject.Properties) {
  $state = $stateProp.Value
  $hasTaxBase = $state.PSObject.Properties.Name -contains "tax_base"
  if ($state.status -in @("source_pending", "pending_extraction")) {
    if ($state.PSObject.Properties.Name -contains "flat_rate") {
      throw "State $($stateProp.Name) is $($state.status) but has flat_rate"
    }
    if ($state.PSObject.Properties.Name -contains "brackets") {
      throw "State $($stateProp.Name) is $($state.status) but has brackets"
    }
    if ($hasTaxBase) {
      throw "State $($stateProp.Name) is $($state.status) but has tax_base"
    }
  }
  if ($state.status -eq "effective" -and !$state.effective_date) {
    throw "State $($stateProp.Name) is effective but missing effective_date"
  }
  if ($state.income_tax_type -eq "none" -and $hasTaxBase) {
    throw "State $($stateProp.Name) has no income tax but has tax_base"
  }
    if ($hasTaxBase) {
      $taxBase = $state.tax_base
      if ($taxBase.start_from -notin $allowedStateTaxBaseStarts) {
        throw "State $($stateProp.Name) tax_base has unsupported start_from $($taxBase.start_from)"
      }
    if (!($taxBase.allows_qbi -is [bool])) {
      throw "State $($stateProp.Name) tax_base allows_qbi must be boolean"
    }
    if (($taxBase.PSObject.Properties.Name -contains "qbi_addback") -and !($taxBase.qbi_addback -is [bool])) {
      throw "State $($stateProp.Name) tax_base qbi_addback must be boolean"
    }
    if ($taxBase.PSObject.Properties.Name -contains "capital_gains_treatment") {
      if ($taxBase.capital_gains_treatment -notin @("ordinary_income")) {
        throw "State $($stateProp.Name) tax_base has unsupported capital_gains_treatment $($taxBase.capital_gains_treatment)"
      }
    }
      if ($taxBase.start_from -eq "federal_agi") {
        if ($taxBase.allows_qbi -eq $true) {
          throw "State $($stateProp.Name) federal_agi tax_base with allows_qbi=true is not modeled"
        }
      $hasStandardDeduction = $taxBase.PSObject.Properties.Name -contains "standard_deduction"
      $usesExemptionAllowance = ($taxBase.PSObject.Properties.Name -contains "uses_exemption_allowance") -and $taxBase.uses_exemption_allowance
      if (!$hasStandardDeduction -and !$usesExemptionAllowance) {
        throw "State $($stateProp.Name) federal_agi tax_base must define standard_deduction or uses_exemption_allowance"
      }
      if ($hasStandardDeduction) {
        foreach ($filingStatus in $requiredStateFilingStatuses) {
          if (!($taxBase.standard_deduction.PSObject.Properties.Name -contains $filingStatus)) {
            throw "State $($stateProp.Name) standard_deduction missing filing status $filingStatus"
          }
        }
      }
      if ($usesExemptionAllowance) {
        if (!$taxBase.exemption_allowance_per_person) {
          throw "State $($stateProp.Name) uses exemption allowance but missing exemption_allowance_per_person"
        }
        $exemptionPhaseoutAgi = $taxBase.exemption_phaseout_agi
        if (!$exemptionPhaseoutAgi) {
          throw "State $($stateProp.Name) uses exemption allowance but missing exemption_phaseout_agi"
        }
        foreach ($filingStatus in $requiredStateFilingStatuses) {
          if (!($exemptionPhaseoutAgi.PSObject.Properties.Name -contains $filingStatus)) {
            throw "State $($stateProp.Name) exemption_phaseout_agi missing filing status $filingStatus"
          }
        }
      }
      Assert-FederalTaxSubtractionShape $taxBase "State $($stateProp.Name)"
      }
      if ($taxBase.start_from -eq "gross_income") {
        if ($taxBase.allows_qbi -eq $true) {
          throw "State $($stateProp.Name) gross_income tax_base with allows_qbi=true is not modeled"
        }
        $hasGrossExemption = $taxBase.PSObject.Properties.Name -contains "exemption_per_person"
        $hasGrossStandardDeduction = $taxBase.PSObject.Properties.Name -contains "standard_deduction"
        $hasNoTaxGrossThreshold = $taxBase.PSObject.Properties.Name -contains "no_tax_gross_income_threshold"
        if ($hasGrossExemption -and $taxBase.exemption_per_person -le 0) {
          throw "State $($stateProp.Name) gross_income exemption_per_person must be positive"
        }
        if ($hasNoTaxGrossThreshold) {
          foreach ($filingStatus in $requiredStateFilingStatuses) {
            if (!($taxBase.no_tax_gross_income_threshold.PSObject.Properties.Name -contains $filingStatus)) {
              throw "State $($stateProp.Name) gross_income no_tax_gross_income_threshold missing filing status $filingStatus"
            }
            if ($taxBase.no_tax_gross_income_threshold.$filingStatus -lt 0) {
              throw "State $($stateProp.Name) gross_income no_tax_gross_income_threshold for $filingStatus must be non-negative"
            }
          }
        }
        if ($hasGrossStandardDeduction) {
          foreach ($filingStatus in $requiredStateFilingStatuses) {
            if (!($taxBase.standard_deduction.PSObject.Properties.Name -contains $filingStatus)) {
              throw "State $($stateProp.Name) gross_income standard_deduction missing filing status $filingStatus"
            }
          }
        }
      }
  }
  if ($state.PSObject.Properties.Name -contains "capital_gains_excise") {
    $capitalGainsExcise = $state.capital_gains_excise
    if (!$capitalGainsExcise.rate) {
      throw "State $($stateProp.Name) capital_gains_excise missing rate"
    }
    if (!$capitalGainsExcise.standard_deduction) {
      throw "State $($stateProp.Name) capital_gains_excise missing standard_deduction"
    }
    if (!($capitalGainsExcise.long_term_only -is [bool])) {
      throw "State $($stateProp.Name) capital_gains_excise long_term_only must be boolean"
    }
    if ($null -eq $capitalGainsExcise.surtax_rate) {
      throw "State $($stateProp.Name) capital_gains_excise missing surtax_rate"
    }
    if ($null -eq $capitalGainsExcise.surtax_threshold) {
      throw "State $($stateProp.Name) capital_gains_excise missing surtax_threshold"
    }
    if (!$capitalGainsExcise.source_ids) {
      throw "State $($stateProp.Name) capital_gains_excise missing source_ids"
    }
    foreach ($sourceId in $capitalGainsExcise.source_ids) {
      if (!$sourceIds.ContainsKey($sourceId)) {
        throw "State $($stateProp.Name) capital_gains_excise references unknown source_id $sourceId"
      }
    }
  }
  if ($state.status -eq "effective" -and $state.income_tax_type -eq "progressive") {
    if (!($state.PSObject.Properties.Name -contains "brackets")) {
      throw "State $($stateProp.Name) is progressive but missing brackets"
    }
    foreach ($filingStatus in $requiredStateFilingStatuses) {
      if (!($state.brackets.PSObject.Properties.Name -contains $filingStatus)) {
        throw "State $($stateProp.Name) progressive brackets missing filing status $filingStatus"
      }
      $brackets = $state.brackets.$filingStatus
      if (!$brackets -or $brackets.Count -lt 1) {
        throw "State $($stateProp.Name) progressive brackets for $filingStatus must not be empty"
      }
      if ($null -ne $brackets[$brackets.Count - 1].up_to) {
        throw "State $($stateProp.Name) progressive final bracket for $filingStatus must have up_to null"
      }
    }
  }
}

if ($states.states.CO.tax_base.start_from -ne "federal_taxable_income") {
  throw "Colorado tax_base must start from federal_taxable_income"
}
if ($states.states.CO.tax_base.qbi_addback -ne $false) {
  throw "Colorado tax_base must not include a QBI addback"
}
foreach ($stateCode in @("CA", "NY", "GA", "IL", "CO", "NJ", "PA")) {
  if ($states.states.$stateCode.tax_base.capital_gains_treatment -ne "ordinary_income") {
    throw "State $stateCode must treat capital gains as ordinary income for crypto state-tax modeling"
  }
}
if ($states.states.NJ.tax_base.start_from -ne "gross_income") {
  throw "New Jersey tax_base must start from gross_income"
}
if ($states.states.NJ.tax_base.exemption_per_person -ne 1000) {
  throw "Unexpected NJ exemption_per_person"
}
if ($states.states.NJ.tax_base.no_tax_gross_income_threshold.single -ne 10000) {
  throw "Unexpected NJ single no-tax gross income threshold"
}
if ($states.states.NJ.tax_base.no_tax_gross_income_threshold.married_filing_jointly -ne 20000) {
  throw "Unexpected NJ MFJ no-tax gross income threshold"
}
if ($states.states.NJ.brackets.single[0].up_to -ne 20000) {
  throw "Unexpected NJ single first bracket cap"
}
if ($states.states.NJ.brackets.married_filing_jointly[2].rate -ne 0.0245) {
  throw "Unexpected NJ MFJ 2.45 percent bracket"
}
if ($states.states.PA.tax_base.start_from -ne "gross_income") {
  throw "Pennsylvania tax_base must start from gross_income"
}
if ($states.states.PA.flat_rate -ne 0.0307) {
  throw "Unexpected PA flat_rate"
}
if ($states.states.OR.tax_base.start_from -ne "federal_agi") {
  throw "Oregon tax_base must start from federal_agi"
}
if ($states.states.OR.tax_base.standard_deduction.single -ne 2835) {
  throw "Unexpected OR single standard deduction"
}
if ($states.states.OR.tax_base.standard_deduction.married_filing_jointly -ne 5670) {
  throw "Unexpected OR MFJ standard deduction"
}
if ($states.states.OR.tax_base.standard_deduction.head_of_household -ne 4560) {
  throw "Unexpected OR HOH standard deduction"
}
if ($states.states.OR.brackets.single[1].up_to -ne 11100) {
  throw "Unexpected OR single second bracket cap"
}
if ($states.states.OR.brackets.married_filing_jointly[1].up_to -ne 22200) {
  throw "Unexpected OR MFJ second bracket cap"
}
if ($states.states.OR.tax_base.federal_tax_subtraction.phaseout_table.single[0].limit -ne 8500) {
  throw "Unexpected OR single federal tax subtraction full limit"
}
if ($states.states.OR.tax_base.federal_tax_subtraction.phaseout_table.married_filing_separately[0].limit -ne 4250) {
  throw "Unexpected OR MFS federal tax subtraction full limit"
}
if ($states.states.OR.tax_base.federal_tax_subtraction.phaseout_table.single[-1].limit -ne 0) {
  throw "Unexpected OR single federal tax subtraction final limit"
}
if ($states.states.WA.capital_gains_excise.standard_deduction -ne 278000) {
  throw "Unexpected WA 2025 capital gains standard deduction"
}
if ($states.states.WA.capital_gains_excise.rate -ne 0.07) {
  throw "Unexpected WA capital gains excise base rate"
}
if ($states.states.WA.capital_gains_excise.surtax_rate -ne 0.029) {
  throw "Unexpected WA capital gains excise surtax rate"
}
if ($states.states.WA.capital_gains_excise.surtax_threshold -ne 1000000) {
  throw "Unexpected WA capital gains excise surtax threshold"
}
if ($states.states.WA.capital_gains_excise.long_term_only -ne $true) {
  throw "WA capital gains excise must be long-term only"
}
# C1: No-tax states spot checks
if ($states.states.AK.income_tax_type -ne "none") {
  throw "Alaska must be income_tax_type none"
}
if ($states.states.AK.status -ne "effective") {
  throw "Alaska must be effective"
}
if ($states.states.NH.income_tax_type -ne "none") {
  throw "New Hampshire must be income_tax_type none"
}
if ($states.states.NH.status -ne "effective") {
  throw "New Hampshire must be effective"
}
if ($states.states.SD.income_tax_type -ne "none") {
  throw "South Dakota must be income_tax_type none"
}
if ($states.states.SD.status -ne "effective") {
  throw "South Dakota must be effective"
}
if ($states.states.TN.income_tax_type -ne "none") {
  throw "Tennessee must be income_tax_type none"
}
if ($states.states.TN.status -ne "effective") {
  throw "Tennessee must be effective"
}
if ($states.states.WY.income_tax_type -ne "none") {
  throw "Wyoming must be income_tax_type none"
}
if ($states.states.WY.status -ne "effective") {
  throw "Wyoming must be effective"
}
if ($states.states.TX.status -ne "effective") {
  throw "Texas must be effective (no longer source_pending)"
}
if ($states.states.TX.income_tax_type -ne "none") {
  throw "Texas must be income_tax_type none"
}

# C2: Flat-tax states spot checks
if ($states.states.AZ.flat_rate -ne 0.025) {
  throw "Unexpected AZ flat_rate"
}
if ($states.states.AZ.status -ne "effective") {
  throw "Arizona must be effective"
}
if ($states.states.ID.flat_rate -ne 0.053) {
  throw "Unexpected ID flat_rate"
}
if ($states.states.IN.flat_rate -ne 0.0305) {
  throw "Unexpected IN flat_rate"
}
if ($states.states.IN.tax_base.start_from -ne "federal_agi") {
  throw "Indiana tax_base must start from federal_agi"
}
if ($states.states.IA.flat_rate -ne 0.038) {
  throw "Unexpected IA flat_rate"
}
if ($states.states.KY.flat_rate -ne 0.04) {
  throw "Unexpected KY flat_rate"
}
if ($states.states.KY.tax_base.standard_deduction.single -ne 3270) {
  throw "Unexpected KY standard deduction"
}
if ($states.states.LA.flat_rate -ne 0.03) {
  throw "Unexpected LA flat_rate"
}
if ($states.states.LA.tax_base.standard_deduction.single -ne 12500) {
  throw "Unexpected LA single standard deduction"
}
if ($states.states.MI.flat_rate -ne 0.0425) {
  throw "Unexpected MI flat_rate"
}
if ($states.states.MS.income_tax_type -ne "progressive") {
  throw "Mississippi must be income_tax_type progressive"
}
if ($states.states.MS.brackets.single[0].rate -ne 0) {
  throw "Unexpected MS first bracket rate (should be 0)"
}
if ($states.states.MS.brackets.single[0].up_to -ne 10000) {
  throw "Unexpected MS zero-bracket cap"
}
if ($states.states.NC.flat_rate -ne 0.0425) {
  throw "Unexpected NC flat_rate"
}
if ($states.states.NC.tax_base.standard_deduction.single -ne 12750) {
  throw "Unexpected NC single standard deduction"
}
if ($states.states.UT.flat_rate -ne 0.045) {
  throw "Unexpected UT flat_rate"
}
if ($states.states.MA.flat_rate -ne 0.05) {
  throw "Unexpected MA flat_rate"
}
if ($states.states.MA.status -ne "effective") {
  throw "Massachusetts must be effective (no longer source_pending)"
}
if ($states.states.MA.surtax.rate -ne 0.04) {
  throw "Unexpected MA surtax rate"
}
if ($states.states.MA.surtax.threshold -ne 1083150) {
  throw "Unexpected MA surtax threshold"
}

# C3a: Progressive states spot checks (2025)
if ($states.states.AR.income_tax_type -ne "progressive") {
  throw "Arkansas must be income_tax_type progressive"
}
if ($states.states.AR.status -ne "effective") {
  throw "Arkansas must be effective"
}
if ($states.states.AR.brackets.single[0].rate -ne 0) {
  throw "Unexpected AR first bracket rate (should be 0)"
}
if ($states.states.AR.brackets.single[-1].rate -ne 0.039) {
  throw "Unexpected AR top rate"
}
if ($states.states.AR.tax_base.standard_deduction.single -ne 2410) {
  throw "Unexpected AR single standard deduction"
}
if ($states.states.DE.income_tax_type -ne "progressive") {
  throw "Delaware must be income_tax_type progressive"
}
if ($states.states.DE.brackets.single[-1].rate -ne 0.066) {
  throw "Unexpected DE top rate"
}
if ($states.states.DE.tax_base.standard_deduction.single -ne 3250) {
  throw "Unexpected DE single standard deduction"
}
if ($states.states.HI.income_tax_type -ne "progressive") {
  throw "Hawaii must be income_tax_type progressive"
}
if ($states.states.HI.brackets.single.Count -ne 12) {
  throw "Hawaii must have 12 brackets for single"
}
if ($states.states.HI.brackets.single[-1].rate -ne 0.11) {
  throw "Unexpected HI top rate"
}
if ($states.states.HI.tax_base.standard_deduction.single -ne 5544) {
  throw "Unexpected HI single standard deduction (should include personal exemption)"
}
if ($states.states.KS.income_tax_type -ne "progressive") {
  throw "Kansas must be income_tax_type progressive"
}
if ($states.states.KS.brackets.single[-1].rate -ne 0.0558) {
  throw "Unexpected KS top rate"
}
if ($states.states.KS.brackets.married_filing_jointly[0].up_to -ne 46000) {
  throw "Unexpected KS MFJ first bracket cap"
}
if ($states.states.KS.tax_base.standard_deduction.single -ne 12765) {
  throw "Unexpected KS single standard deduction (should include personal exemption)"
}
if ($states.states.ME.income_tax_type -ne "progressive") {
  throw "Maine must be income_tax_type progressive"
}
if ($states.states.ME.brackets.single[-2].up_to -ne 1000000) {
  throw "Unexpected ME surcharge threshold"
}
if ($states.states.ME.brackets.single[-1].rate -ne 0.0915) {
  throw "Unexpected ME top rate"
}
if ($states.states.ME.tax_base.standard_deduction.single -ne 20150) {
  throw "Unexpected ME single standard deduction (should include personal exemption)"
}
if ($states.states.MD.income_tax_type -ne "progressive") {
  throw "Maryland must be income_tax_type progressive"
}
if ($states.states.MD.brackets.single.Count -ne 10) {
  throw "Maryland must have 10 brackets for single (incl new 6.25%/6.50%)"
}
if ($states.states.MD.brackets.single[-1].rate -ne 0.065) {
  throw "Unexpected MD top rate"
}
if ($states.states.MD.tax_base.standard_deduction.single -ne 6550) {
  throw "Unexpected MD single standard deduction (should include personal exemption)"
}
if ($states.states.MO.income_tax_type -ne "progressive") {
  throw "Missouri must be income_tax_type progressive"
}
if ($states.states.MO.brackets.single[0].rate -ne 0) {
  throw "Unexpected MO first bracket rate (should be 0)"
}
if ($states.states.MO.brackets.single[-1].rate -ne 0.047) {
  throw "Unexpected MO top rate"
}
if ($states.states.MT.income_tax_type -ne "progressive") {
  throw "Montana must be income_tax_type progressive"
}
if ($states.states.MT.brackets.single[-1].rate -ne 0.059) {
  throw "Unexpected MT top rate"
}
if ($states.states.MT.brackets.married_filing_jointly[0].up_to -ne 42200) {
  throw "Unexpected MT MFJ first bracket cap"
}
if ($states.states.NE.income_tax_type -ne "progressive") {
  throw "Nebraska must be income_tax_type progressive"
}
if ($states.states.NE.brackets.single[-1].rate -ne 0.052) {
  throw "Unexpected NE top rate"
}
if ($states.states.NE.tax_base.standard_deduction.single -ne 8600) {
  throw "Unexpected NE single standard deduction"
}

# C3b: Progressive states second half spot checks (2025)
if ($states.states.NM.income_tax_type -ne "progressive") {
  throw "New Mexico must be income_tax_type progressive"
}
if ($states.states.NM.brackets.single[-1].rate -ne 0.059) {
  throw "Unexpected NM top rate"
}
if ($states.states.NM.brackets.single.Count -ne 6) {
  throw "NM must have 6 brackets for single"
}
if ($states.states.ND.income_tax_type -ne "progressive") {
  throw "North Dakota must be income_tax_type progressive"
}
if ($states.states.ND.brackets.single[0].rate -ne 0) {
  throw "Unexpected ND first bracket rate (should be 0)"
}
if ($states.states.ND.brackets.single[-1].rate -ne 0.025) {
  throw "Unexpected ND top rate"
}
if ($states.states.OH.income_tax_type -ne "progressive") {
  throw "Ohio must be income_tax_type progressive"
}
if ($states.states.OH.brackets.single[0].rate -ne 0) {
  throw "Unexpected OH first bracket rate (should be 0)"
}
if ($states.states.OH.brackets.single[-1].rate -ne 0.03125) {
  throw "Unexpected OH top rate (should be 3.125%)"
}
if ($states.states.OH.tax_base.standard_deduction.single -ne 1900) {
  throw "Unexpected OH single standard deduction (personal exemption >80k tier)"
}
if ($states.states.OK.income_tax_type -ne "progressive") {
  throw "Oklahoma must be income_tax_type progressive"
}
if ($states.states.OK.brackets.single[-1].rate -ne 0.0475) {
  throw "Unexpected OK top rate"
}
if ($states.states.OK.tax_base.standard_deduction.single -ne 7350) {
  throw "Unexpected OK single standard deduction (incl personal exemption)"
}
if ($states.states.RI.income_tax_type -ne "progressive") {
  throw "Rhode Island must be income_tax_type progressive"
}
if ($states.states.RI.brackets.single[-1].rate -ne 0.0599) {
  throw "Unexpected RI top rate"
}
if ($states.states.RI.tax_base.standard_deduction.single -ne 16000) {
  throw "Unexpected RI single standard deduction (incl personal exemption)"
}
if ($states.states.SC.income_tax_type -ne "progressive") {
  throw "South Carolina must be income_tax_type progressive"
}
if ($states.states.SC.brackets.single[0].rate -ne 0) {
  throw "Unexpected SC first bracket rate (should be 0)"
}
if ($states.states.SC.brackets.single[-1].rate -ne 0.06) {
  throw "Unexpected SC top rate"
}
if ($states.states.VA.income_tax_type -ne "progressive") {
  throw "Virginia must be income_tax_type progressive"
}
if ($states.states.VA.brackets.single[-1].rate -ne 0.0575) {
  throw "Unexpected VA top rate"
}
if ($states.states.VA.brackets.single[0].up_to -ne 3000) {
  throw "Unexpected VA first bracket cap"
}
if ($states.states.VA.tax_base.standard_deduction.single -ne 9430) {
  throw "Unexpected VA single standard deduction (incl personal exemption)"
}
if ($states.states.VT.income_tax_type -ne "progressive") {
  throw "Vermont must be income_tax_type progressive"
}
if ($states.states.VT.brackets.single[-1].rate -ne 0.0875) {
  throw "Unexpected VT top rate"
}
if ($states.states.VT.tax_base.PSObject.Properties.Name -contains "standard_deduction") {
  throw "VT must not define a separate standard_deduction when starting from federal taxable income"
}
if ($states.states.WV.income_tax_type -ne "progressive") {
  throw "West Virginia must be income_tax_type progressive"
}
if ($states.states.WV.brackets.single[-1].rate -ne 0.0482) {
  throw "Unexpected WV top rate"
}
if ($states.states.WV.brackets.single.Count -ne 5) {
  throw "WV must have 5 brackets"
}
if ($states.states.WV.tax_base.standard_deduction.single -ne 2000) {
  throw "Unexpected WV single standard deduction (personal exemption only)"
}

# C4: Complex states spot checks (2025)
if ($states.states.AL.income_tax_type -ne "progressive") {
  throw "Alabama must be income_tax_type progressive"
}
if ($states.states.AL.brackets.single[-1].rate -ne 0.05) {
  throw "Unexpected AL top rate"
}
if ($states.states.AL.brackets.single.Count -ne 3) {
  throw "AL must have 3 brackets"
}
if ($states.states.AL.tax_base.standard_deduction.single -ne 4500) {
  throw "Unexpected AL single standard deduction (incl personal exemption)"
}
if ($null -eq $states.states.AL.tax_base.federal_tax_subtraction) {
  throw "AL must have federal_tax_subtraction"
}
if ($states.states.CT.income_tax_type -ne "progressive") {
  throw "Connecticut must be income_tax_type progressive"
}
if ($states.states.CT.brackets.single.Count -ne 7) {
  throw "CT must have 7 brackets for single"
}
if ($states.states.CT.brackets.single[-1].rate -ne 0.0699) {
  throw "Unexpected CT top rate"
}
if ($states.states.CT.tax_base.standard_deduction.single -ne 0) {
  throw "CT must have zero standard deduction (uses personal exemption credits)"
}
if ($states.states.DC.income_tax_type -ne "progressive") {
  throw "DC must be income_tax_type progressive"
}
if ($states.states.DC.brackets.single.Count -ne 7) {
  throw "DC must have 7 brackets"
}
if ($states.states.DC.brackets.single[-1].rate -ne 0.1075) {
  throw "Unexpected DC top rate"
}
if ($states.states.DC.tax_base.standard_deduction.single -ne 15000) {
  throw "Unexpected DC single standard deduction"
}
if ($states.states.MN.income_tax_type -ne "progressive") {
  throw "Minnesota must be income_tax_type progressive"
}
if ($states.states.MN.brackets.single[-1].rate -ne 0.0985) {
  throw "Unexpected MN top rate"
}
if ($states.states.MN.tax_base.standard_deduction.single -ne 14950) {
  throw "Unexpected MN single standard deduction"
}
if ($states.states.WI.income_tax_type -ne "progressive") {
  throw "Wisconsin must be income_tax_type progressive"
}
if ($states.states.WI.brackets.single[-1].rate -ne 0.0765) {
  throw "Unexpected WI top rate"
}
if ($states.states.WI.tax_base.standard_deduction.single -ne 14260) {
  throw "Unexpected WI single standard deduction (incl personal exemption)"
}

if ($states.states.CA.tax_base.standard_deduction.single -ne 5540) {
  throw "Unexpected CA single standard deduction"
}
if ($states.states.CA.tax_base.standard_deduction.married_filing_separately -ne 5540) {
  throw "Unexpected CA MFS standard deduction"
}
if ($states.states.CA.tax_base.standard_deduction.married_filing_jointly -ne 11080) {
  throw "Unexpected CA MFJ standard deduction"
}
if ($states.states.CA.tax_base.standard_deduction.qualifying_surviving_spouse -ne 11080) {
  throw "Unexpected CA QSS standard deduction"
}
if ($states.states.CA.tax_base.standard_deduction.head_of_household -ne 11080) {
  throw "Unexpected CA HOH standard deduction"
}
if ($states.states.NY.tax_base.standard_deduction.single -ne 8000) {
  throw "Unexpected NY single standard deduction"
}
if ($states.states.NY.tax_base.standard_deduction.married_filing_separately -ne 8000) {
  throw "Unexpected NY MFS standard deduction"
}
if ($states.states.NY.tax_base.standard_deduction.married_filing_jointly -ne 16050) {
  throw "Unexpected NY MFJ standard deduction"
}
if ($states.states.NY.tax_base.standard_deduction.qualifying_surviving_spouse -ne 16050) {
  throw "Unexpected NY QSS standard deduction"
}
if ($states.states.NY.tax_base.standard_deduction.head_of_household -ne 11200) {
  throw "Unexpected NY HOH standard deduction"
}
if ($states.states.GA.tax_base.standard_deduction.married_filing_jointly -ne 24000) {
  throw "Unexpected GA MFJ standard deduction"
}
foreach ($filingStatus in @("single", "married_filing_separately", "qualifying_surviving_spouse", "head_of_household")) {
  if ($states.states.GA.tax_base.standard_deduction.$filingStatus -ne 12000) {
    throw "Unexpected GA standard deduction for $filingStatus"
  }
}
if ($states.states.IL.tax_base.exemption_allowance_per_person -ne 2625) {
  throw "Unexpected IL exemption allowance per person"
}
if ($states.states.IL.tax_base.exemption_phaseout_agi.married_filing_jointly -ne 500000) {
  throw "Unexpected IL MFJ exemption phaseout AGI"
}
foreach ($filingStatus in @("single", "head_of_household", "married_filing_separately", "qualifying_surviving_spouse")) {
  if ($states.states.IL.tax_base.exemption_phaseout_agi.$filingStatus -ne 250000) {
    throw "Unexpected IL exemption phaseout AGI for $filingStatus"
  }
}

$nexus = Read-Json "data/tax_years/2025/us_nexus.json"
foreach ($thresholdProp in $nexus.thresholds.PSObject.Properties) {
  $threshold = $thresholdProp.Value
  if ($threshold.status -eq "source_pending" -and ($threshold.PSObject.Properties.Name -contains "sales_amount")) {
    throw "Nexus threshold $($thresholdProp.Name) is source_pending but has sales_amount"
  }
  if ($threshold.status -ne "source_pending" -and !$threshold.effective_date) {
    throw "Nexus threshold $($thresholdProp.Name) missing effective_date"
  }
  if ($threshold.status -ne "source_pending") {
    if (!($threshold.PSObject.Properties.Name -contains "comparison")) {
      throw "Nexus threshold $($thresholdProp.Name) missing comparison"
    }
    if ($threshold.comparison -notin @("gt", "gte")) {
      throw "Nexus threshold $($thresholdProp.Name) has unsupported comparison $($threshold.comparison)"
    }
  }
}

$capitalGains = Read-Json "data/tax_years/2025/us_capital_gains.json"
$requiredFilingStatuses = @(
  "single",
  "married_filing_jointly",
  "qualifying_surviving_spouse",
  "head_of_household",
  "married_filing_separately"
)

if ($capitalGains.status -eq "effective" -and !$capitalGains.effective_date) {
  throw "Capital gains effective rule file missing effective_date"
}

$ltcg = $capitalGains.long_term_capital_gains
if (!$ltcg) { throw "Capital gains file missing long_term_capital_gains" }
if (!$ltcg.effective_date) { throw "long_term_capital_gains missing effective_date" }
if (!$ltcg.citation) { throw "long_term_capital_gains missing citation" }
if (!$ltcg.brackets) { throw "long_term_capital_gains missing brackets" }

foreach ($filingStatus in $requiredFilingStatuses) {
  if (!($ltcg.brackets.PSObject.Properties.Name -contains $filingStatus)) {
    throw "LTCG brackets missing filing status $filingStatus"
  }
  $brackets = $ltcg.brackets.$filingStatus
  if ($brackets.Count -ne 3) {
    throw "LTCG brackets for $filingStatus must contain exactly three brackets"
  }
  if ($null -ne $brackets[$brackets.Count - 1].up_to) {
    throw "LTCG final bracket for $filingStatus must have up_to null"
  }
}

if ($ltcg.brackets.married_filing_separately[0].up_to -ne 48350) {
  throw "Unexpected 2025 MFS LTCG zero-rate threshold"
}
if ($ltcg.brackets.married_filing_separately[1].up_to -ne 300000) {
  throw "Unexpected 2025 MFS LTCG 15-percent threshold"
}
if ($ltcg.brackets.qualifying_surviving_spouse[0].up_to -ne 96700) {
  throw "Unexpected 2025 QSS LTCG zero-rate threshold"
}
if ($ltcg.brackets.qualifying_surviving_spouse[1].up_to -ne 600050) {
  throw "Unexpected 2025 QSS LTCG 15-percent threshold"
}

$stcg = $capitalGains.short_term_capital_gains
if (!$stcg) { throw "Capital gains file missing short_term_capital_gains" }
if ($stcg.treatment -ne "ordinary_income") {
  throw "Short-term capital gains must be ordinary_income treatment"
}
if (!$stcg.effective_date) { throw "short_term_capital_gains missing effective_date" }
if (!$stcg.citation) { throw "short_term_capital_gains missing citation" }

$niit = $capitalGains.net_investment_income_tax
if (!$niit) { throw "Capital gains file missing net_investment_income_tax" }
if ($niit.rate -ne 0.038) { throw "Unexpected NIIT rate" }
if (!$niit.effective_date) { throw "net_investment_income_tax missing effective_date" }
if (!$niit.citation) { throw "net_investment_income_tax missing citation" }
if ($niit.applies_to -ne "lesser_of_net_investment_income_or_magi_over_threshold") {
  throw "Unexpected NIIT applies_to formula"
}
foreach ($filingStatus in $requiredFilingStatuses) {
  if (!($niit.magi_thresholds.PSObject.Properties.Name -contains $filingStatus)) {
    throw "NIIT MAGI thresholds missing filing status $filingStatus"
  }
}
if ($niit.magi_thresholds.single -ne 200000) { throw "Unexpected NIIT single threshold" }
if ($niit.magi_thresholds.head_of_household -ne 200000) { throw "Unexpected NIIT HOH threshold" }
if ($niit.magi_thresholds.married_filing_jointly -ne 250000) { throw "Unexpected NIIT MFJ threshold" }
if ($niit.magi_thresholds.qualifying_surviving_spouse -ne 250000) { throw "Unexpected NIIT QSS threshold" }
if ($niit.magi_thresholds.married_filing_separately -ne 125000) { throw "Unexpected NIIT MFS threshold" }

$federal2026 = Read-Json "data/tax_years/2026/us_federal.json"
if ($federal2026.rule_version -ne "us-2026-federal-v0.1") {
  throw "Unexpected 2026 federal rule_version"
}
if ($federal2026.standard_deduction.single -ne 16100) {
  throw "Unexpected 2026 single standard deduction"
}
if ($federal2026.standard_deduction.married_filing_jointly -ne 32200) {
  throw "Unexpected 2026 MFJ standard deduction"
}
if ($federal2026.standard_deduction.married_filing_separately -ne 16100) {
  throw "Unexpected 2026 MFS standard deduction"
}
if ($federal2026.standard_deduction.head_of_household -ne 24150) {
  throw "Unexpected 2026 HOH standard deduction"
}
if ($federal2026.ordinary_income_brackets.single[0].up_to -ne 12400) {
  throw "Unexpected first 2026 single federal bracket cap"
}
if ($federal2026.ordinary_income_brackets.married_filing_separately[5].up_to -ne 384350) {
  throw "Unexpected 2026 MFS 35-percent federal bracket cap"
}
if ($null -ne $federal2026.ordinary_income_brackets.head_of_household[6].up_to) {
  throw "2026 HOH final federal bracket must have up_to null"
}

$fica2026 = Read-Json "data/tax_years/2026/us_fica.json"
if ($fica2026.social_security.wage_base -ne 184500) {
  throw "Unexpected 2026 Social Security wage base"
}
if ($fica2026.social_security.employee_rate -ne 0.062) {
  throw "Unexpected 2026 employee Social Security rate"
}
if ($fica2026.additional_medicare.employee_rate -ne 0.009) {
  throw "Unexpected 2026 Additional Medicare rate"
}
if ($fica2026.self_employment.net_earnings_multiplier -ne 0.9235) {
  throw "Unexpected 2026 self-employment net earnings multiplier"
}

$feie2026 = Read-Json "data/tax_years/2026/us_feie.json"
if ($feie2026.foreign_earned_income_exclusion.maximum_exclusion -ne 132900) {
  throw "Unexpected 2026 FEIE maximum exclusion"
}
if ($feie2026.foreign_earned_income_exclusion.physical_presence_days -ne 330) {
  throw "Unexpected 2026 FEIE physical presence days"
}

$qbi2026 = Read-Json "data/tax_years/2026/us_qbi.json"
$expectedQbi2026Thresholds = @{
  single = 201750
  head_of_household = 201750
  married_filing_separately = 201775
  qualifying_surviving_spouse = 201750
  married_filing_jointly = 403500
}
$expectedQbi2026Windows = @{
  single = 75000
  head_of_household = 75000
  married_filing_separately = 75000
  qualifying_surviving_spouse = 75000
  married_filing_jointly = 150000
}
if ($qbi2026.qbi_deduction.rate -ne 0.2) { throw "Unexpected 2026 QBI deduction rate" }
if ($qbi2026.qbi_deduction.wage_ubia_limit.half_w2_wages_rate -ne 0.5) {
  throw "Unexpected 2026 QBI half_w2_wages_rate"
}
if ($qbi2026.qbi_deduction.wage_ubia_limit.quarter_w2_wages_rate -ne 0.25) {
  throw "Unexpected 2026 QBI quarter_w2_wages_rate"
}
if ($qbi2026.qbi_deduction.wage_ubia_limit.ubia_rate -ne 0.025) {
  throw "Unexpected 2026 QBI ubia_rate"
}
foreach ($filingStatus in $requiredQbiFilingStatuses) {
  $threshold = $qbi2026.qbi_deduction.taxable_income_threshold.$filingStatus
  $window = $qbi2026.qbi_deduction.phase_in_window.$filingStatus
  $upperLimit = $qbi2026.qbi_deduction.upper_limit.$filingStatus
  if ($threshold -ne $expectedQbi2026Thresholds[$filingStatus]) {
    throw "Unexpected 2026 QBI threshold for $filingStatus"
  }
  if ($window -ne $expectedQbi2026Windows[$filingStatus]) {
    throw "Unexpected 2026 QBI phase-in window for $filingStatus"
  }
  if ($upperLimit -ne ($threshold + $window)) {
    throw "2026 QBI upper_limit for $filingStatus must equal threshold + phase_in_window"
  }
}

$capitalGains2026 = Read-Json "data/tax_years/2026/us_capital_gains.json"
$ltcg2026 = $capitalGains2026.long_term_capital_gains
if ($ltcg2026.brackets.single[0].up_to -ne 49450) {
  throw "Unexpected 2026 single LTCG zero-rate threshold"
}
if ($ltcg2026.brackets.single[1].up_to -ne 545500) {
  throw "Unexpected 2026 single LTCG 15-percent threshold"
}
if ($ltcg2026.brackets.married_filing_jointly[0].up_to -ne 98900) {
  throw "Unexpected 2026 MFJ LTCG zero-rate threshold"
}
if ($ltcg2026.brackets.married_filing_jointly[1].up_to -ne 613700) {
  throw "Unexpected 2026 MFJ LTCG 15-percent threshold"
}
if ($ltcg2026.brackets.married_filing_separately[1].up_to -ne 306850) {
  throw "Unexpected 2026 MFS LTCG 15-percent threshold"
}
if ($capitalGains2026.net_investment_income_tax.rate -ne 0.038) {
  throw "Unexpected 2026 NIIT rate"
}

$states2026 = Read-Json "data/tax_years/2026/us_states.json"
foreach ($stateProp in $states2026.states.PSObject.Properties) {
  if ($stateProp.Value.state_parameter_year -ne 2025) {
    throw "2026 state $($stateProp.Name) must declare state_parameter_year 2025"
  }
  if ($stateProp.Value.PSObject.Properties.Name -contains "tax_base") {
    Assert-FederalTaxSubtractionShape $stateProp.Value.tax_base "2026 state $($stateProp.Name)"
  }
}
if ($states2026.states.NJ.tax_base.start_from -ne "gross_income") {
  throw "2026 New Jersey tax_base must start from gross_income"
}
if ($states2026.states.NJ.tax_base.exemption_per_person -ne 1000) {
  throw "Unexpected 2026 NJ exemption_per_person"
}
if ($states2026.states.NJ.tax_base.no_tax_gross_income_threshold.single -ne 10000) {
  throw "Unexpected 2026 NJ single no-tax gross income threshold"
}
if ($states2026.states.NJ.tax_base.no_tax_gross_income_threshold.married_filing_jointly -ne 20000) {
  throw "Unexpected 2026 NJ MFJ no-tax gross income threshold"
}
if ($states2026.states.PA.tax_base.start_from -ne "gross_income") {
  throw "2026 Pennsylvania tax_base must start from gross_income"
}
if ($states2026.states.PA.flat_rate -ne 0.0307) {
  throw "Unexpected 2026 PA flat_rate"
}
if ($states2026.states.OR.tax_base.start_from -ne "federal_agi") {
  throw "2026 Oregon tax_base must start from federal_agi"
}
if ($states2026.states.OR.tax_base.standard_deduction.single -ne 2835) {
  throw "Unexpected 2026 OR single standard deduction"
}
if ($states2026.states.OR.brackets.single[1].up_to -ne 11100) {
  throw "Unexpected 2026 OR single second bracket cap"
}
if ($states2026.states.OR.tax_base.federal_tax_subtraction.phaseout_table.single[0].limit -ne 8500) {
  throw "Unexpected 2026 OR single federal tax subtraction full limit"
}
if ($states2026.states.OR.tax_base.federal_tax_subtraction.phaseout_table.married_filing_separately[0].limit -ne 4250) {
  throw "Unexpected 2026 OR MFS federal tax subtraction full limit"
}

# C1: 2026 no-tax states spot checks
if ($states2026.states.AK.income_tax_type -ne "none") {
  throw "2026 Alaska must be income_tax_type none"
}
if ($states2026.states.AK.status -ne "effective") {
  throw "2026 Alaska must be effective"
}
if ($states2026.states.NH.income_tax_type -ne "none") {
  throw "2026 New Hampshire must be income_tax_type none"
}
if ($states2026.states.NH.status -ne "effective") {
  throw "2026 New Hampshire must be effective"
}
if ($states2026.states.SD.income_tax_type -ne "none") {
  throw "2026 South Dakota must be income_tax_type none"
}
if ($states2026.states.TN.income_tax_type -ne "none") {
  throw "2026 Tennessee must be income_tax_type none"
}
if ($states2026.states.WY.income_tax_type -ne "none") {
  throw "2026 Wyoming must be income_tax_type none"
}
if ($states2026.states.TX.status -ne "effective") {
  throw "2026 Texas must be effective"
}
if ($states2026.states.TX.income_tax_type -ne "none") {
  throw "2026 Texas must be income_tax_type none"
}

# C2: 2026 flat-tax states spot checks
if ($states2026.states.AZ.flat_rate -ne 0.025) {
  throw "2026 Unexpected AZ flat_rate"
}
if ($states2026.states.ID.flat_rate -ne 0.053) {
  throw "2026 Unexpected ID flat_rate"
}
if ($states2026.states.IN.flat_rate -ne 0.03) {
  throw "2026 Unexpected IN flat_rate"
}
if ($states2026.states.KY.flat_rate -ne 0.04) {
  throw "2026 Unexpected KY flat_rate"
}
if ($states2026.states.NC.flat_rate -ne 0.0425) {
  throw "2026 Unexpected NC flat_rate"
}
if ($states2026.states.MA.flat_rate -ne 0.05) {
  throw "2026 Unexpected MA flat_rate"
}
if ($states2026.states.MA.status -ne "effective") {
  throw "2026 Massachusetts must be effective"
}
if ($states2026.states.MA.surtax.rate -ne 0.04) {
  throw "2026 Unexpected MA surtax rate"
}

$nexus2026 = Read-Json "data/tax_years/2026/us_nexus.json"
foreach ($thresholdProp in $nexus2026.thresholds.PSObject.Properties) {
  if ($thresholdProp.Value.state_parameter_year -ne 2025) {
    throw "2026 nexus threshold $($thresholdProp.Name) must declare state_parameter_year 2025"
  }
}

Write-Output "Step 1 data validation passed."
