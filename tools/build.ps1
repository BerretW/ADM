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
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
$reportPath = Join-Path $distPath $reportName
$report = [System.Collections.Generic.List[string]]::new()

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
    Add-ReportLine "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    [System.IO.File]::WriteAllLines($reportPath, $report.ToArray(), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Report: $reportPath"
}

function Invoke-Step {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments
    )

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
    if ($exitCode -ne 0) {
        Add-ReportLine "Output (last 80 lines):"
        foreach ($line in ($output | Select-Object -Last 80)) {
            Add-ReportLine "$line"
        }
        Add-ReportLine "RESULT: FAILED (exit code $exitCode)"
        throw "$Name failed with exit code $exitCode"
    }
    Add-ReportLine "RESULT: PASS"
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

    $pythonChecks = @(
        @{ Name = "Python version"; Args = @("-c", "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'; print(sys.version)") },
        @{ Name = "Python unit tests"; Args = @("-m", "unittest", "adm_blender.tests.test_skeleton_profiles",
            "adm_blender.tests.test_container", "adm_blender.tests.test_draft4",
            "adm_blender.tests.test_gputex", "adm_blender.tests.test_bvh", "-v") },
        @{ Name = "ADM standard tests"; Args = @(".\adm-standard\tools\run_tests.py") },
        @{ Name = "Interactive surface conformance"; Args = @(".\adm-standard\tools\test_interactive_surfaces.py") },
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
        "test_interactive_blender.py",
        "test_workflow.py",
        "test_terrain_workflow.py",
        "test_skeleton_blender.py",
        "test_material_slots.py",
        "test_shader_harness.py",
        "test_shader_profiles.py",
        "test_shader_preview.py",
        "test_texture_formats.py",
        "test_component_animation_blender.py",
        "test_mixamo_animation_blender.py",
        "test_bvh_blender.py"
    )
    foreach ($test in $blenderTests) {
        $testPath = ".\adm_blender\tests\$test"
        Invoke-Step -Name "Blender: $test" -Executable $blenderExe -Arguments @(
            "-b", "--factory-startup", "--python-exit-code", "1", "--python", $testPath
        )
    }

    if ($CheckOnly) {
        Add-ReportLine ""
        Add-ReportLine "PACKAGE: SKIPPED (-CheckOnly; version unchanged)"
        Add-ReportLine "RESULT: PASS"
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
    Write-Report
}
catch {
    Add-ReportLine ""
    Add-ReportLine "RESULT: FAILED"
    Add-ReportLine "ERROR: $($_.Exception.Message)"
    if ($versionChanged) {
        [System.IO.File]::WriteAllText($manifestPath, $manifestOriginal, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText($exportPath, $exportOriginal, [System.Text.UTF8Encoding]::new($false))
        Add-ReportLine "VERSION: rolled back because the build did not complete successfully"
    }
    Write-Report
    exit 1
}
