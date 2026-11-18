param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $root "adm_blender\blender_manifest.toml"
$exportPath = Join-Path $root "adm_blender\blender\export_adm.py"
$distPath = Join-Path $root "dist"
$manifestOriginal = [System.IO.File]::ReadAllText($manifestPath)
$exportOriginal = [System.IO.File]::ReadAllText($exportPath)
$versionMatch = [regex]::Match($manifestOriginal, '(?m)^version = "(\d+)\.(\d+)\.(\d+)"$')
if (-not $versionMatch.Success) {
    throw "Could not read a SemVer version from $manifestPath"
}

$currentVersion = "{0}.{1}.{2}" -f $versionMatch.Groups[1].Value, $versionMatch.Groups[2].Value,
    $versionMatch.Groups[3].Value
$nextVersion = "{0}.{1}.{2}" -f $versionMatch.Groups[1].Value, $versionMatch.Groups[2].Value,
    ([int]$versionMatch.Groups[3].Value + 1)
$buildVersion = if ($CheckOnly) { $currentVersion } else { $nextVersion }
$reportName = if ($CheckOnly) { "check-report-$currentVersion.txt" } else { "build-report-$nextVersion.txt" }
$qaReportStem = if ($CheckOnly) { "qa-report-$currentVersion" } else { "qa-report-$nextVersion" }
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
$reportPath = Join-Path $distPath $reportName
$qaJsonPath = Join-Path $distPath "$qaReportStem.json"
$qaMarkdownPath = Join-Path $distPath "$qaReportStem.md"
$report = [System.Collections.Generic.List[string]]::new()
$testResults = [System.Collections.Generic.List[object]]::new()
$startedAt = [DateTimeOffset]::Now
$commit = $null
$worktreeChangedFiles = @()
$blenderVersion = $null
$buildStatus = "IN_PROGRESS"
$buildError = $null

function Add-ReportLine {
    param([string]$Text)
    $report.Add($Text) | Out-Null
}

Add-ReportLine "ADM Tools build report"
Add-ReportLine "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
Add-ReportLine "Mode: $(if ($CheckOnly) { 'check only' } else { 'version bump, tests, and package' })"
Add-ReportLine "Current version: $currentVersion"
Add-ReportLine "Target version: $buildVersion"
$versionChanged = $false

function Write-Report {
    $finishedAt = [DateTimeOffset]::Now
    $allCases = @($testResults | ForEach-Object { $_.cases })
    Add-ReportLine "Finished: $($finishedAt.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    [System.IO.File]::WriteAllLines($reportPath, $report.ToArray(), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Report: $reportPath"

    $qaReport = [ordered]@{
        schema_version = "1.0"
        status = $buildStatus
        plugin_version_tested = $currentVersion
        plugin_version_target = $buildVersion
        blender_version = $blenderVersion
        commit = $commit
        worktree_dirty = ($worktreeChangedFiles.Count -gt 0)
        worktree_changed_files = $worktreeChangedFiles
        started_at = $startedAt.ToString("o")
        finished_at = $finishedAt.ToString("o")
        test_case_counts = [ordered]@{
            pass = @($allCases | Where-Object { $_.status -eq "PASS" }).Count
            fail = @($allCases | Where-Object { $_.status -eq "FAIL" }).Count
            skip = @($allCases | Where-Object { $_.status -eq "SKIP" }).Count
        }
        test_step_counts = [ordered]@{
            pass = @($testResults | Where-Object { $_.status -eq "PASS" }).Count
            fail = @($testResults | Where-Object { $_.status -eq "FAIL" }).Count
            skip = @($testResults | Where-Object { $_.status -eq "SKIP" }).Count
        }
        reproduction_fixtures = @(
            [ordered]@{ kind = "generated"; path = "adm_blender/tests/test_workflow.py" },
            [ordered]@{ kind = "reference"; path = "adm-standard/fixtures/valid/" },
            [ordered]@{ kind = "external"; path = "adm_blender/tests/external_data/ (local, ignored)" }
        )
        tests = @($testResults.ToArray())
        import_export_errors = @($testResults | Where-Object {
            $_.status -eq "FAIL" -and $_.name -match "(?i)import|export|workflow"
        })
        property_changes = [ordered]@{
            status = "NOT_REPORTED_BY_CURRENT_TESTS"
            changes = $null
        }
        performance = [ordered]@{
            unit = "milliseconds"
            metric_scope = "successful ADM model import/export operations"
            test_durations = @($testResults | ForEach-Object {
                [ordered]@{ name = $_.name; duration_ms = $_.duration_ms }
            })
            import_export_metrics = @($testResults | ForEach-Object { $_.metrics })
        }
        known_limitations = @(
            "The current round-trip suites do not emit a machine-readable list of changed or lost ADM properties.",
            "Only successful ADM model import/export operations executed with the QA metrics flag are timed.",
            "The external-asset catalog requires local rights attestations and does not establish legal permission."
        )
        error = $buildError
    }
    $json = ConvertTo-Json -InputObject $qaReport -Depth 10
    [System.IO.File]::WriteAllText($qaJsonPath, $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false))

    $markdown = [System.Collections.Generic.List[string]]::new()
    $markdown.Add("# ADM QA report")
    $markdown.Add("")
    $markdown.Add("- **Result:** $buildStatus")
    $markdown.Add("- **Plugin version tested:** $currentVersion")
    $markdown.Add("- **Target version:** $buildVersion")
    $markdown.Add("- **Blender:** $(if ($blenderVersion) { $blenderVersion } else { 'not available' })")
    $markdown.Add("- **Commit:** $(if ($commit) { $commit } else { 'not available' })")
    $markdown.Add("- **Worktree dirty:** $($worktreeChangedFiles.Count -gt 0)")
    $markdown.Add("")
    $markdown.Add("## Reproduction fixtures")
    $markdown.Add('- Generated: `adm_blender/tests/test_workflow.py` and the generated triangle in the external catalog.')
    $markdown.Add('- Reference: `adm-standard/fixtures/valid/`.')
    $markdown.Add('- External: `adm_blender/tests/external_data/` (local and ignored by Git).')
    $markdown.Add("")
    $markdown.Add("| Test | Result | Duration (ms) | Skip reason |")
    $markdown.Add("| --- | --- | ---: | --- |")
    foreach ($test in $testResults) {
        $skipReason = ($test.skip_reasons -join "; ").Replace("|", "\|")
        $markdown.Add("| $($test.name.Replace('|', '\|')) | $($test.status) | $($test.duration_ms) | $skipReason |")
    }
    $markdown.Add("")
    $markdown.Add("## Test cases")
    $markdown.Add("")
    $markdown.Add("| Suite | Test case | Result | Reason |")
    $markdown.Add("| --- | --- | --- | --- |")
    foreach ($test in $testResults) {
        foreach ($case in $test.cases) {
            $caseReason = if ($case.reason) { $case.reason.Replace("|", "\|") } else { "" }
            $markdown.Add("| $($test.name.Replace('|', '\|')) | $($case.name.Replace('|', '\|')) | " +
                "$($case.status) | $caseReason |")
        }
    }
    $markdown.Add("")
    $markdown.Add("## Successful import/export timings")
    $markdown.Add("")
    $markdown.Add("| Suite | Operation | Duration (ms) | Status |")
    $markdown.Add("| --- | --- | ---: | --- |")
    foreach ($test in $testResults) {
        foreach ($metric in $test.metrics) {
            $markdown.Add("| $($test.name.Replace('|', '\|')) | $($metric.operation) | " +
                "$($metric.duration_ms) | $($metric.status) |")
        }
    }
    $markdown.Add("")
    if ($buildError) {
        $markdown.Add("## Build error")
        $markdown.Add("")
        $markdown.Add('```text')
        $markdown.Add($buildError)
        $markdown.Add('```')
        $markdown.Add("")
    }
    $markdown.Add("## Import/export errors")
    $importExportErrors = @($qaReport.import_export_errors)
    if ($importExportErrors.Count -eq 0) {
        $markdown.Add("None recorded.")
    }
    else {
        foreach ($failure in $importExportErrors) {
            $markdown.Add("")
            $markdown.Add("### $($failure.name)")
            $markdown.Add('```text')
            $markdown.Add($failure.traceback -join [Environment]::NewLine)
            $markdown.Add('```')
        }
    }
    $markdown.Add("")
    $markdown.Add("## Property comparison and performance limitations")
    $markdown.Add("- ADM property changes: not reported by the current round-trip tests.")
    $markdown.Add("- Import/export timings cover only successful ADM model operations in the QA runner.")
    [System.IO.File]::WriteAllLines($qaMarkdownPath, $markdown.ToArray(),
        [System.Text.UTF8Encoding]::new($false))
    Write-Host "QA JSON: $qaJsonPath"
    Write-Host "QA Markdown: $qaMarkdownPath"
}

function Invoke-Step {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    Add-ReportLine ""
    Add-ReportLine "STEP: $Name"
    Write-Host "== $Name"
    Push-Location $root
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $output) {
            Write-Host "$line"
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
        Pop-Location
    }
    $timer.Stop()
    $skipReasons = @($output | ForEach-Object {
        if ("$_" -match '^\s*SKIP:\s*(.+)$') { $Matches[1] }
    } | Where-Object { $_ })
    $explicitSkip = @($output | Where-Object { "$_" -match '^\s*RESULT:\s*SKIP(?:\s*[:(]|$)' })
    $caseResults = [System.Collections.Generic.List[object]]::new()
    $stepMetrics = [System.Collections.Generic.List[object]]::new()
    foreach ($line in $output) {
        $text = "$line"
        if ($text -match '^\s*ADM_QA_METRIC:\s*(\{.*\})\s*$') {
            try {
                $metric = ConvertFrom-Json -InputObject $Matches[1]
                if ($metric.operation -notin @("model_import", "model_export") -or
                    $metric.status -ne "PASS" -or $metric.duration_ms -lt 0) {
                    throw "invalid QA operation metric"
                }
                $stepMetrics.Add([pscustomobject][ordered]@{
                    operation = $metric.operation
                    duration_ms = [double]$metric.duration_ms
                    status = $metric.status
                }) | Out-Null
            }
            catch {
                $caseResults.Add([pscustomobject][ordered]@{
                    name = "Malformed QA operation metric"
                    status = "FAIL"
                    reason = $_.Exception.Message
                }) | Out-Null
            }
        }
        elseif ($text -match '^\s*ok\s+(.*)$') {
            $caseResults.Add([pscustomobject][ordered]@{ name = $Matches[1]; status = "PASS"; reason = $null }) |
                Out-Null
        }
        elseif ($text -match '^\s*PASS:\s*(.+)$') {
            $caseResults.Add([pscustomobject][ordered]@{ name = $Matches[1]; status = "PASS"; reason = $null }) |
                Out-Null
        }
        elseif ($text -match '^\s*FAIL\s+(.*)$') {
            $caseResults.Add([pscustomobject][ordered]@{ name = $Matches[1]; status = "FAIL"; reason = $null }) |
                Out-Null
        }
        elseif ($text -match '^\s*FAIL:\s*(.*)$') {
            $caseResults.Add([pscustomobject][ordered]@{ name = $Matches[1]; status = "FAIL"; reason = $null }) |
                Out-Null
        }
        elseif ($text -match '^\s*SKIP:\s*(.+)$') {
            $caseResults.Add([pscustomobject][ordered]@{ name = $Matches[1]; status = "SKIP"; reason = $Matches[1] }) |
                Out-Null
        }
        elseif ($text -match '^\s*(test_[A-Za-z0-9_]+(?:\s+\([^)]*\))?)\s+\.\.\.\s+(ok|FAIL|ERROR|skipped)(?:\s+(.*))?$') {
            $caseStatus = if ($Matches[2] -eq "ok") { "PASS" } elseif ($Matches[2] -eq "skipped") { "SKIP" } else { "FAIL" }
            $caseResults.Add([pscustomobject][ordered]@{
                name = $Matches[1]
                status = $caseStatus
                reason = if ($caseStatus -eq "SKIP") { $Matches[3] } else { $null }
            }) | Out-Null
        }
    }
    $caseFailures = @($caseResults | Where-Object { $_.status -eq "FAIL" })
    $casePasses = @($caseResults | Where-Object { $_.status -eq "PASS" })
    $caseSkips = @($caseResults | Where-Object { $_.status -eq "SKIP" })
    $stepStatus = if ($exitCode -ne 0 -or $caseFailures.Count -gt 0) {
        "FAIL"
    } elseif ($explicitSkip.Count -gt 0 -or ($caseSkips.Count -gt 0 -and $casePasses.Count -eq 0)) {
        "SKIP"
    } else {
        "PASS"
    }
    $traceback = if ($stepStatus -eq "FAIL") {
        @($output | Select-Object -Last 80 | ForEach-Object { "$_" })
    } else {
        @()
    }
    $testResults.Add([pscustomobject][ordered]@{
        name = $Name
        status = $stepStatus
        duration_ms = [math]::Round($timer.Elapsed.TotalMilliseconds, 2)
        skip_reasons = $skipReasons
        cases = @($caseResults.ToArray())
        metrics = @($stepMetrics.ToArray())
        error = if ($exitCode -ne 0) {
            "Exit code $exitCode"
        } elseif ($caseFailures.Count -gt 0) {
            "Test output reported failing cases"
        } else {
            $null
        }
        traceback = $traceback
    }) | Out-Null
    if ($stepStatus -eq "FAIL") {
        Add-ReportLine "Output (last 80 lines):"
        foreach ($line in ($output | Select-Object -Last 80)) {
            Add-ReportLine "$line"
        }
        Add-ReportLine "RESULT: FAILED (exit code $exitCode)"
        throw "$Name failed"
    }
    if ($stepStatus -eq "SKIP") {
        Add-ReportLine "RESULT: SKIP"
    }
    else {
        Add-ReportLine "RESULT: PASS"
    }
    foreach ($reason in $skipReasons) {
        Add-ReportLine "SKIP: $reason"
    }
}

try {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $python) {
        throw "Python 3.11+ was not found on PATH."
    }
    $pythonExe = $python.Source

    $blenderExe = $env:BLENDER_EXE
    if (-not $blenderExe) {
        $blenderCommand = Get-Command blender.exe -ErrorAction SilentlyContinue
        if ($blenderCommand) {
            $blenderExe = $blenderCommand.Source
        }
        else {
            $blenderExe = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
        }
    }
    if (-not (Test-Path -LiteralPath $blenderExe -PathType Leaf)) {
        throw "Blender executable not found: $blenderExe. Set BLENDER_EXE to its full path."
    }
    $commitOutput = & git -C $root rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0) {
        $commit = ($commitOutput | Select-Object -First 1).ToString().Trim()
    }
    $gitStatusOutput = & git -C $root status --porcelain 2>$null
    if ($LASTEXITCODE -eq 0) {
        $worktreeChangedFiles = @($gitStatusOutput | ForEach-Object {
            $line = "$_"
            if ($line.Length -gt 3) { $line.Substring(3).Trim() }
        } | Where-Object { $_ })
    }
    $blenderVersionOutput = & $blenderExe --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query Blender version: $blenderExe"
    }
    $blenderVersion = ($blenderVersionOutput | Select-Object -First 1).ToString().Trim()

    $pythonChecks = @(
        @{ Name = "Python version"; Args = @("-c", "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'; print(sys.version)") },
        @{ Name = "Python unit tests"; Args = @("-m", "unittest", "adm_blender.tests.test_skeleton_profiles",
            "adm_blender.tests.test_container", "adm_blender.tests.test_draft4",
            "adm_blender.tests.test_gputex", "adm_blender.tests.test_bvh",
            "adm_blender.tests.test_shader_math", "adm_blender.tests.test_terrain_partition",
            "adm_blender.tests.test_external_asset_catalog", "adm_blender.tests.test_qa_metrics", "-v") },
        @{ Name = "ADM standard tests"; Args = @(".\adm-standard\tools\run_tests.py") },
        @{ Name = "Interactive surface conformance"; Args = @(".\adm-standard\tools\test_interactive_surfaces.py") },
        @{ Name = "ADM profile tests"; Args = @(".\adm-standard\tools\test_profiles.py") },
        @{ Name = "Shader vertex-mask conformance"; Args = @(".\adm-standard\tools\test_shader_vertex_masks.py") },
        @{ Name = "Independent conformance"; Args = @(".\adm-standard\tools\test_independent_conformance.py") },
        @{ Name = "Shader registry and development changes"; Args = @(
            ".\adm-standard\tools\build_shader_registry.py", "--check") },
        @{ Name = "Shader registry development-change records"; Args = @(
            ".\adm-standard\tools\check_shader_registry_changes.py") },
        @{ Name = "Shader registry tests"; Args = @(".\adm-standard\tools\test_shader_registry.py") },
        @{ Name = "Reference-test catalog"; Args = @(".\adm-standard\tools\test_reference_catalog.py") }
    )
    foreach ($check in $pythonChecks) {
        Invoke-Step -Name $check.Name -Executable $pythonExe -Arguments $check.Args
    }

    $blenderTests = @(
        "test_fixtures.py",
        "test_import_transaction_blender.py",
        "test_export_transaction.py",
        "test_interactive_blender.py",
        "test_workflow.py",
        "test_terrain_workflow.py",
        "test_skeleton_blender.py",
        "test_material_slots.py",
        "test_shader_harness.py",
        "test_shader_profiles.py",
        "test_shader_preview.py",
        "test_lod_generator.py",
        "test_texture_formats.py",
        "test_component_animation_blender.py",
        "test_mixamo_animation_blender.py",
        "test_bvh_blender.py",
        "test_external_assets_blender.py",
        "test_external_catalog_blender.py"
    )
    $priorQaMetrics = $env:ADM_QA_METRICS
    try {
        foreach ($test in $blenderTests) {
            if ($test -in @("test_import_transaction_blender.py", "test_export_transaction.py")) {
                Remove-Item Env:ADM_QA_METRICS -ErrorAction SilentlyContinue
            }
            else {
                $env:ADM_QA_METRICS = "1"
            }
            $testPath = ".\adm_blender\tests\$test"
            Invoke-Step -Name "Blender: $test" -Executable $blenderExe -Arguments @(
                "-b", "--factory-startup", "--python-exit-code", "1", "--python", $testPath
            )
        }
    }
    finally {
        if ($null -eq $priorQaMetrics) {
            Remove-Item Env:ADM_QA_METRICS -ErrorAction SilentlyContinue
        }
        else {
            $env:ADM_QA_METRICS = $priorQaMetrics
        }
    }

    if ($CheckOnly) {
        Add-ReportLine ""
        Add-ReportLine "PACKAGE: SKIPPED (-CheckOnly; version unchanged)"
        Add-ReportLine "RESULT: PASS"
        $buildStatus = "PASS"
        Write-Report
        exit 0
    }

    $manifestUpdated = [regex]::Replace($manifestOriginal, '(?m)^version = "\d+\.\d+\.\d+"$',
        "version = `"$nextVersion`"", 1)
    if ($manifestUpdated -eq $manifestOriginal) {
        throw "Could not update the manifest version."
    }
    $generatorPattern = 'ADM Tools for Blender ' + [regex]::Escape($currentVersion) + ' \(ADM 1\.0\)'
    $exportUpdated = [regex]::Replace($exportOriginal, $generatorPattern,
        "ADM Tools for Blender $nextVersion (ADM 1.0)", 1)
    if ($exportUpdated -eq $exportOriginal) {
        throw "GENERATOR in export_adm.py does not match manifest version $currentVersion."
    }
    $versionChanged = $true
    [System.IO.File]::WriteAllText($manifestPath, $manifestUpdated, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($exportPath, $exportUpdated, [System.Text.UTF8Encoding]::new($false))
    Add-ReportLine ""
    Add-ReportLine "VERSION: $currentVersion -> $nextVersion (patch)"

    $buildStartedUtc = [DateTime]::UtcNow
    Invoke-Step -Name "Build Blender extension ZIP" -Executable $blenderExe -Arguments @(
        "--command", "extension", "build", "--source-dir", ".\adm_blender", "--output-dir", ".\dist"
    )
    $zipPath = Join-Path $distPath "adm_tools-$nextVersion.zip"
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        throw "Blender completed without producing the expected package: $zipPath"
    }
    $zipInfo = Get-Item -LiteralPath $zipPath
    if ($zipInfo.Length -eq 0 -or $zipInfo.LastWriteTimeUtc -lt $buildStartedUtc.AddSeconds(-2)) {
        throw "The expected package was not freshly written: $zipPath"
    }
    Add-ReportLine "PACKAGE: $zipPath"
    Add-ReportLine "RESULT: PASS"
    $buildStatus = "PASS"
    Write-Report
}
catch {
    Add-ReportLine ""
    Add-ReportLine "RESULT: FAILED"
    Add-ReportLine "ERROR: $($_.Exception.Message)"
    $buildStatus = "FAIL"
    $buildError = $_.Exception.ToString()
    if ($versionChanged) {
        [System.IO.File]::WriteAllText($manifestPath, $manifestOriginal, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText($exportPath, $exportOriginal, [System.Text.UTF8Encoding]::new($false))
        Add-ReportLine "VERSION: rolled back because the build did not complete successfully"
    }
    Write-Report
    exit 1
}
