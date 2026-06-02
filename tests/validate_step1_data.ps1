$ErrorActionPreference = "Stop"

function Read-Json($Path) {
  if (!(Test-Path -LiteralPath $Path)) {
    throw "Missing JSON file: $Path"
  }
  return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

$manifest = Read-Json "data/sources/us/2025/source_manifest.json"
if (!$manifest.sources -or $manifest.sources.Count -lt 1) {
  throw "source_manifest.json must contain at least one source"
}

$sourceIds = @{}
foreach ($source in $manifest.sources) {
  if (!$source.source_id) { throw "Source missing source_id" }
  if (!$source.local_path) { throw "Source $($source.source_id) missing local_path" }
  if (!$source.content_hash) { throw "Source $($source.source_id) missing content_hash" }
  if (!(Test-Path -LiteralPath $source.local_path)) {
    throw "Archived source file missing: $($source.local_path)"
  }
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.local_path).Hash
  if ($actualHash -ne $source.content_hash) {
    throw "Hash mismatch for $($source.source_id): expected $($source.content_hash), got $actualHash"
  }
  $sourceIds[$source.source_id] = $true
}

$ruleFiles = @(
  "data/tax_years/2025/us_federal.json",
  "data/tax_years/2025/us_fica.json",
  "data/tax_years/2025/us_feie.json",
  "data/tax_years/2025/us_states.json",
  "data/tax_years/2025/us_nexus.json",
  "data/tax_years/2025/us_capital_gains.json"
)

foreach ($file in $ruleFiles) {
  $doc = Read-Json $file
  if (!$doc.schema_version) { throw "$file missing schema_version" }
  if ($doc.tax_year -ne 2025) { throw "$file tax_year must be 2025" }
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
foreach ($stateProp in $states.states.PSObject.Properties) {
  $state = $stateProp.Value
  if ($state.status -in @("source_pending", "pending_extraction")) {
    if ($state.PSObject.Properties.Name -contains "flat_rate") {
      throw "State $($stateProp.Name) is $($state.status) but has flat_rate"
    }
    if ($state.PSObject.Properties.Name -contains "brackets") {
      throw "State $($stateProp.Name) is $($state.status) but has brackets"
    }
  }
  if ($state.status -eq "effective" -and !$state.effective_date) {
    throw "State $($stateProp.Name) is effective but missing effective_date"
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

Write-Output "Step 1 data validation passed."
