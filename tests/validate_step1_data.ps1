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
  "data/tax_years/2025/us_nexus.json"
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

Write-Output "Step 1 data validation passed."
