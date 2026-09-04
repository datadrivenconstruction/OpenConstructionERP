# Guards the Python detection in scripts/install.ps1.
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT
# The subject is the shipped scripts/install.ps1, read from disk and
# dot-sourced with everything from the "Main" banner down removed, so nothing
# is downloaded and nothing is installed. These cases therefore prove the
# branch the installer takes given a candidate list. They are not an install
# that ran end to end, and nobody runs one of those in CI, so a green result
# here should not be read as "the installer works".
#
# WHY IT EXISTS
# install.ps1 used to ask "does the name python resolve to something", by
# running `python --version` and reading the banner. That is a different
# question from "is there a Python 3.12 or newer here that I can run", and the
# two answers differ in both directions: `python` can resolve to an unrelated
# virtual environment that happens to be on PATH, and a perfectly good 3.12 can
# be present under `py -3.12` alone, which is the ordinary state after the
# official Windows installer, whose "Add python.exe to PATH" box is unchecked
# while the launcher is always installed. The defect is one that comes back,
# because whoever next thinks the launcher entries look redundant will be
# looking at a machine where `python` happens to resolve. Hence the structural
# case below, which fails if those entries are removed.
#
# HOW TO RUN
#   pwsh -File scripts/tests/install-ps1-python-detection.tests.ps1
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

# ── The subject, with Main removed ───────────────────────────────────
$src = Join-Path (Split-Path -Parent $PSScriptRoot) "install.ps1"
if (-not (Test-Path $src)) { Write-Host "cannot find $src"; exit 1 }
$raw = Get-Content $src -Raw

Write-Host "parse"
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($raw, [ref]$null, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { Write-Host "  $($_.Extent.StartLineNumber): $($_.Message)" }
    Write-Host "install.ps1 does not parse, nothing else can be trusted"
    exit 1
}
Assert-That -What "install.ps1 parses" -Condition $true

$banner = [regex]::Match($raw, '(?m)^#[^\r\n]*\bMain\b')
if (-not $banner.Success) { Write-Host "cannot find the Main banner, refusing to guess where to cut"; exit 1 }

$stubs = Join-Path $env:TEMP "oe-install-probe-$PID"
New-Item -ItemType Directory -Force -Path $stubs | Out-Null

try {
    $defs = Join-Path $stubs "install-defs.ps1"
    Set-Content -Path $defs -Value $raw.Substring(0, $banner.Index) -Encoding utf8
    . $defs

    # ── Stub interpreters ────────────────────────────────────────────
    # A .cmd that prints a version and exits with the verdict is enough to be
    # a candidate: the probe runs the candidate and reads what it printed. Real
    # interpreters would make the too-old case depend on what this machine
    # happens to have installed, and the message a person gets in that case is
    # the whole point of the change being guarded.
    function New-StubInterpreter {
        param([string] $Name, [string] $Prints, [int] $Exit)
        $path = Join-Path $stubs "$Name.cmd"
        Set-Content -Path $path -Encoding ascii -Value @(
            "@echo off",
            "echo $Prints",
            "exit /b $Exit"
        )
        return $path
    }

    $tooOld     = New-StubInterpreter -Name "oe-stub-old"        -Prints "3.11.0" -Exit 1
    $goodEnough = New-StubInterpreter -Name "oe-stub-new"        -Prints "3.12.7" -Exit 0
    $notPython  = New-StubInterpreter -Name "oe-stub-not-python" -Prints "hello"  -Exit 0
    # Named 3.9, reports 3.12: the name and the interpreter disagree on purpose.
    $liesLow    = New-StubInterpreter -Name "oe-stub-python3.9"  -Prints "3.12.7" -Exit 0
    # Named 3.12, reports 3.11: the same disagreement, the other way round.
    $liesHigh   = New-StubInterpreter -Name "oe-stub-python3.12" -Prints "3.11.0" -Exit 1

    function Reset-Search {
        $script:OE_PYTHON_SEARCHED = $false
        $script:OE_PYTHON_FOUND = $null
        $script:OE_PYTHON_REJECTED = @()
    }

    function Get-Message {
        # What Write-NoPython312 puts on screen, as lines.
        return @(Write-NoPython312 6>&1 | ForEach-Object { [string]$_ })
    }

    # ── The launcher entries are not decoration ──────────────────────
    Write-Host ""
    Write-Host "the shipped candidate list"
    $shipped = @($OE_PYTHON_CANDIDATES | ForEach-Object { $_ -join " " })
    Assert-That -What "'py -3.12' is a candidate" -Condition ($shipped -contains "py -3.12") `
        -Detail "list is: $($shipped -join ', ')"
    Assert-That -What "'py -3' is a candidate" -Condition ($shipped -contains "py -3") `
        -Detail "the official installer leaves PATH alone but always installs the launcher"
    # Both positions have to be real. Comparing a missing entry's -1 against a
    # present one would pass while saying nothing, which is the failure mode
    # this whole file exists to avoid.
    $iLauncher = [array]::IndexOf($shipped, "py -3")
    $iBare = [array]::IndexOf($shipped, "python")
    Assert-That -What "the launcher is tried before bare python" `
        -Condition ($iLauncher -ge 0 -and $iBare -ge 0 -and $iLauncher -lt $iBare) `
        -Detail "bare python is the entry most likely to be an unrelated venv; list is: $($shipped -join ', ')"

    # ── A candidate that is too old ──────────────────────────────────
    Write-Host ""
    Write-Host "a candidate exists but is too old"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @($tooOld) )
    $found = Find-Python312
    Assert-That -What "nothing is selected" -Condition ($null -eq $found)
    Assert-That -What "Test-Python312 is false" -Condition (-not (Test-Python312))
    $tooOldMessage = Get-Message
    Assert-That -What "the message names what it found" `
        -Condition ([bool](($tooOldMessage -join "`n") -match "Found, but too old")) `
        -Detail ($tooOldMessage -join " | ")
    Assert-That -What "it names the version it found, not just the name" `
        -Condition ([bool](($tooOldMessage -join "`n") -match "3\.11\.0"))

    # ── No candidate at all ──────────────────────────────────────────
    Write-Host ""
    Write-Host "no candidate exists at all"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @("oe-no-such-python"), @("oe-also-missing", "-3") )
    $found = Find-Python312
    Assert-That -What "nothing is selected" -Condition ($null -eq $found)
    Assert-That -What "Test-Python312 is false" -Condition (-not (Test-Python312))
    $absentMessage = Get-Message
    Assert-That -What "nothing is claimed to have been found" `
        -Condition (-not ([bool](($absentMessage -join "`n") -match "Found, but too old")))

    # Both endings are the same ending. A too-old candidate may add a line
    # naming itself, and may add nothing else: same requirement, same advice,
    # same exit. This is the assertion that fails if somebody gives one of the
    # two paths its own wording and lets them drift.
    $adviceOnly = @($tooOldMessage | Where-Object { $_ -notmatch "Found, but too old" })
    Assert-That -What "too old and absent give the same message apart from the naming line" `
        -Condition (($adviceOnly -join "`n") -eq ($absentMessage -join "`n")) `
        -Detail "too old: $($tooOldMessage -join ' | ')  absent: $($absentMessage -join ' | ')"

    # ── Something that answers but is not a Python ───────────────────
    Write-Host ""
    Write-Host "a candidate that resolves but is not a Python"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @($notPython) )
    $found = Find-Python312
    Assert-That -What "nothing is selected" -Condition ($null -eq $found)
    Assert-That -What "it is not reported as a too-old Python" `
        -Condition ($script:OE_PYTHON_REJECTED.Count -eq 0) `
        -Detail "rejected: $($script:OE_PYTHON_REJECTED -join ', ')"

    # ── The search does not stop at the first name that resolves ─────
    Write-Host ""
    Write-Host "the loop keeps going past a candidate that is too old"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @($tooOld), @($goodEnough) )
    $found = Find-Python312
    Assert-That -What "the usable one further down the list wins" `
        -Condition ($null -ne $found -and $found.Version -eq "3.12.7") `
        -Detail "got: $($found | Out-String)"

    # ── The verdict comes from the interpreter, not from the name ────
    Write-Host ""
    Write-Host "name and interpreter disagree"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @($liesHigh), @($liesLow) )
    $found = Find-Python312
    Assert-That -What "a candidate named 3.12 that reports 3.11 is rejected" `
        -Condition ($script:OE_PYTHON_REJECTED.Count -eq 1)
    Assert-That -What "a candidate named 3.9 that reports 3.12 is accepted" `
        -Condition ($null -ne $found -and $found.Version -eq "3.12.7") `
        -Detail "got: $($found | Out-String)"

    # ── This machine, whatever it has ────────────────────────────────
    Write-Host ""
    Write-Host "the shipped list on this machine"
    Reset-Search
    $OE_PYTHON_CANDIDATES = @( @("py", "-3.12"), @("py", "-3"), @("python3.12"), @("python3"), @("python") )
    $real = Find-Python312
    if ($null -eq $real) {
        Write-Host "  skip this machine has no Python 3.12 or newer; rejected: $($script:OE_PYTHON_REJECTED -join ', ')"
    } else {
        $parts = $real.Version -split '\.'
        $atLeast312 = ([int]$parts[0] -gt 3) -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 12)
        Assert-That -What "what it picked really is 3.12 or newer" -Condition $atLeast312 `
            -Detail "picked '$($real.Display)' = $($real.Version)"

        # Install-Pip builds the venv with the interpreter that was selected
        # rather than respelling `python`, which is the half of the defect that
        # a version check alone would not have caught.
        $venv = Join-Path $stubs "venv"
        $exe = $real.Exe
        $venvArgs = @($real.Args)
        & $exe @venvArgs -m venv $venv 2>&1 | Out-Null
        $venvPython = Join-Path $venv "Scripts\python.exe"
        if (Test-Path $venvPython) {
            $built = (& $venvPython -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>&1 | Select-Object -First 1)
            Assert-That -What "the venv is built by the interpreter that was selected" `
                -Condition ([string]$built -eq $real.Version) `
                -Detail "venv is $built, selected was $($real.Version)"
        } else {
            Write-Host "  skip the selected interpreter could not create a venv here"
        }
    }

    # ── The branch a person actually lands on ────────────────────────
    # Main is cut off, so the dispatcher is lifted out of the shipped text and
    # run with the three installers stubbed. Terminating on a line that is
    # nothing but "}" is deliberate: "}" alone at the start of a line also
    # begins "} elseif", which would cut the chain after its first branch.
    $dispatch = [regex]::Match($raw, '(?sm)if \(Test-Docker\) \{.*?^\}\r?$').Value
    if (-not $dispatch) {
        Write-Host "cannot isolate the dispatcher from install.ps1"
        $script:Failed += "dispatcher could not be isolated"
    } else {
        function Test-Docker { $false }
        function Test-Uv { $false }
        function Install-Docker { Write-Host "would install via Docker" }
        function Install-Uv { Write-Host "would install uv" }
        function Install-Pip { Write-Host "would install via pip" }

        function Get-Branch {
            param([array] $Candidates)
            Reset-Search
            $script:OE_PYTHON_CANDIDATES = $Candidates
            return (@(Invoke-Expression $dispatch 6>&1 | ForEach-Object { [string]$_ }) -join "`n")
        }

        Write-Host ""
        Write-Host "the dispatcher"
        $branch = Get-Branch -Candidates @( @($goodEnough) )
        Assert-That -What "a usable Python goes to pip and is named" `
            -Condition ([bool]($branch -match "3\.12\.7" -and $branch -match "pip")) -Detail $branch

        $branch = Get-Branch -Candidates @( @($tooOld) )
        Assert-That -What "a too-old Python says so rather than claiming none was found" `
            -Condition ([bool]($branch -match "older than 3\.12")) -Detail $branch

        $branch = Get-Branch -Candidates @( @("oe-no-such-python") )
        Assert-That -What "no Python at all says no Python was found" `
            -Condition ([bool]($branch -match "No Docker or Python found")) -Detail $branch
    }
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
