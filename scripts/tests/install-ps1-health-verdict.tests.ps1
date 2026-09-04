# Guards the health verdict in scripts/install.ps1.
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT
# The subject is Get-HealthVerdict, read from the shipped scripts/install.ps1
# and dot-sourced with everything from the "Main" banner down removed. No
# Docker, no network, no install. These cases prove which branch the installer
# takes given a health response, and nothing about whether an install works.
#
# WHY IT EXISTS
# install.ps1 waited for the status to be the literal string "healthy" and
# reported everything else as "health check did not pass within 60s". That was
# survivable while degraded was nearly unreachable. It stopped being survivable
# in 16.8.0, which made an enabled module that fails to load degrade the
# status, a state the endpoint could not previously reach. So the population of
# installs answering "degraded" grows in the same release that this script
# starts calling them failures, and a person whose product is running and
# usable is told it did not install.
#
# The distinction that matters is inside "degraded", not around it. The same
# word covers a module that did not load, where every page still works, and a
# database the process cannot reach, where nothing does. A test that only
# checked "degraded is not reported as a failure" would pass while telling
# somebody with an unreachable database that their install is fine, so the two
# are separated below and each is asserted against the other.
#
# HOW TO RUN
#   pwsh -File scripts/tests/install-ps1-health-verdict.tests.ps1
# Exit code 0 means every case passed. Windows only, and nothing in CI runs it.

$ErrorActionPreference = "Continue"

if ($env:OS -ne "Windows_NT") {
    Write-Host "SKIP: install.ps1 is a Windows script, there is nothing to exercise here."
    exit 0
}

$script:Passed = 0
$script:Failed = @()

function Assert-That {
    param(
        [Parameter(Mandatory)] [string] $What,
        [Parameter(Mandatory)] [bool]   $Condition,
        [string]                        $Detail = ""
    )
    if ($Condition) {
        $script:Passed++
        Write-Host "  ok   $What"
    } else {
        $script:Failed += $What
        Write-Host "  FAIL $What"
        if ($Detail) { Write-Host "       $Detail" }
    }
}

# -- The subject, with Main removed ----------------------------------
$src = Join-Path (Split-Path -Parent $PSScriptRoot) "install.ps1"
if (-not (Test-Path $src)) { Write-Host "cannot find $src"; exit 1 }
$raw = Get-Content $src -Raw

$banner = [regex]::Match($raw, '(?m)^#[^\r\n]*\bMain\b')
if (-not $banner.Success) { Write-Host "cannot find the Main banner, refusing to guess where to cut"; exit 1 }

$stubs = Join-Path $env:TEMP "oe-health-probe-$PID"
New-Item -ItemType Directory -Force -Path $stubs | Out-Null

try {
    $defs = Join-Path $stubs "install-defs.ps1"
    Set-Content -Path $defs -Value $raw.Substring(0, $banner.Index) -Encoding utf8
    . $defs

    # A health response, shaped the way Invoke-RestMethod hands one over.
    function New-Health {
        param([string] $Status, [string] $Database = "ok", [int] $Loaded = 190, [int] $Enabled = 190)
        return [pscustomobject]@{
            status          = $Status
            database        = $Database
            modules_loaded  = $Loaded
            modules_enabled = $Enabled
        }
    }

    Write-Host ""
    Write-Host "a healthy install"
    Assert-That -What "is reported as running" `
        -Condition ((Get-HealthVerdict (New-Health -Status "healthy")) -eq "healthy")

    Write-Host ""
    Write-Host "a degraded install whose database is reachable"
    $verdict = Get-HealthVerdict (New-Health -Status "degraded" -Loaded 189)
    Assert-That -What "is not reported as a failure" `
        -Condition ($verdict -ne "no-answer") -Detail "got $verdict"
    Assert-That -What "is told apart from an unreachable database" `
        -Condition ($verdict -eq "degraded") -Detail "got $verdict"

    Write-Host ""
    Write-Host "a degraded install that cannot reach its database"
    # The case that stops this from being a test that merely waves degraded
    # through. Same status string, opposite meaning for the person reading it.
    $verdict = Get-HealthVerdict (New-Health -Status "degraded" -Database "error")
    Assert-That -What "is not called running" `
        -Condition ($verdict -ne "degraded") -Detail "got $verdict"
    Assert-That -What "names the database rather than the modules" `
        -Condition ($verdict -eq "database") -Detail "got $verdict"

    Write-Host ""
    Write-Host "the two degraded cases are not the same verdict"
    # Asserted directly, because both halves above could pass while the
    # function returned one constant for anything degraded.
    $withDb = Get-HealthVerdict (New-Health -Status "degraded")
    $noDb = Get-HealthVerdict (New-Health -Status "degraded" -Database "error")
    Assert-That -What "one status string yields two verdicts" `
        -Condition ($withDb -ne $noDb) -Detail "both were $withDb"

    Write-Host ""
    Write-Host "nothing ever answered"
    Assert-That -What "is reported as no answer" `
        -Condition ((Get-HealthVerdict $null) -eq "no-answer")

    Write-Host ""
    Write-Host "a status this script does not recognise"
    # Reassuring somebody about a word we do not understand is the failure
    # this branch exists to prevent.
    Assert-That -What "is not reported as running" `
        -Condition ((Get-HealthVerdict (New-Health -Status "starting")) -eq "no-answer")
    Assert-That -What "an empty status is not reported as running" `
        -Condition ((Get-HealthVerdict (New-Health -Status "")) -eq "no-answer")

    Write-Host ""
    Write-Host "the structural case"
    # Fails if somebody puts the old test back. The point of the change is that
    # the wait loop accepts degraded, so a loop that only breaks on healthy
    # would leave every degraded install spinning out the full budget and then
    # being reported as never having answered.
    $loop = [regex]::Match($raw, 'Invoke-RestMethod[\s\S]{0,400}?\}\s*catch')
    Assert-That -What "the wait loop stops on degraded, not only on healthy" `
        -Condition ([bool]($loop.Value -match 'degraded')) -Detail $loop.Value

    Assert-That -What "no message hard-codes the wait in seconds" `
        -Condition (-not ($raw -match 'did not pass within 60s'))
} finally {
    Remove-Item -Recurse -Force $stubs -ErrorAction SilentlyContinue
}

Write-Host ""
if ($script:Failed.Count -gt 0) {
    Write-Host "$($script:Failed.Count) failed, $script:Passed passed"
    $script:Failed | ForEach-Object { Write-Host "  $_" }
    exit 1
}
Write-Host "$script:Passed passed"
exit 0
