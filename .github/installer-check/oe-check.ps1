# Temporary helper for the installer upgrade check on wip/installer-upgrade-185.
# Never merged to main. Every function writes to the step log and returns data;
# a hard failure throws, which fails the step.
$ErrorActionPreference = 'Stop'
$script:Report = Join-Path $env:RUNNER_TEMP 'oe-report.txt'

function Say([string]$m) {
  $line = "$(Get-Date -Format HH:mm:ss) $m"
  Write-Host $line
  Add-Content -LiteralPath $script:Report -Value $line -Encoding utf8
}

function Fail([string]$m) { Say "RED: $m"; throw $m }

function Show-Installer([string]$path) {
  $h = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  $s = Get-AuthenticodeSignature -LiteralPath $path
  Say "installer $path bytes=$((Get-Item -LiteralPath $path).Length) sha256=$h signature=$($s.Status)"
}

function Get-UninstallKey {
  Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\OpenConstructionERP' -ErrorAction SilentlyContinue
}

function Wait-Uninstallers {
  # The NSIS uninstaller copies itself to TEMP as Au_.exe and returns at once.
  for ($i = 0; $i -lt 360; $i++) {
    if (-not (Get-Process -Name 'Au_' -ErrorAction SilentlyContinue)) { return }
    Start-Sleep 5
  }
  Fail 'uninstaller copy still running after 30 minutes'
}

function Install-Silent([string]$installer, [string]$dir) {
  # One string, never an array: Start-Process quotes an element with spaces, and
  # NSIS takes /D= unquoted as the rest of the command line.
  $args_ = if ($dir) { "/S /D=$dir" } else { '/S' }
  $t = Get-Date
  $p = Start-Process -FilePath $installer -ArgumentList $args_ -PassThru -Wait
  Wait-Uninstallers
  Say "install $([IO.Path]::GetFileName($installer)) exit=$($p.ExitCode) seconds=$([int]((Get-Date)-$t).TotalSeconds)"
  if ($p.ExitCode -ne 0) { Fail "installer exit code $($p.ExitCode)" }
  $k = Get-UninstallKey
  Say "uninstall key: version=$($k.DisplayVersion) location=$($k.InstallLocation)"
}

function Show-Layout([string]$app) {
  $f = Get-ChildItem -LiteralPath $app -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum
  $onedir = Test-Path -LiteralPath (Join-Path $app 'server\_internal')
  $onefile = Test-Path -LiteralPath (Join-Path $app 'openconstructionerp-server.exe')
  Say "layout $app files=$($f.Count) MB=$([int]($f.Sum/1MB)) onedir=$onedir onefile_exe=$onefile"
  return [pscustomobject]@{ Onedir = $onedir; Onefile = $onefile }
}

function Start-App([string]$app, [string]$data, [int]$budget = 1500) {
  $ll = Join-Path $data 'desktop-launcher.log'
  $before = if (Test-Path -LiteralPath $ll) { @(Get-Content -LiteralPath $ll).Count } else { 0 }
  $t = Get-Date
  $p = Start-Process -FilePath (Join-Path $app 'OpenConstructionERP.exe') -PassThru
  Say "launcher started pid=$($p.Id)"
  $port = $null
  while (((Get-Date) - $t).TotalSeconds -lt $budget) {
    Start-Sleep 5
    if ($p.HasExited) {
      Show-LauncherLog $data $before
      Fail "launcher exited early with code $($p.ExitCode)"
    }
    if (-not $port -and (Test-Path -LiteralPath $ll)) {
      $m = Get-Content -LiteralPath $ll | Select-Object -Skip $before | Select-String -Pattern 'selected backend port (\d+)' | Select-Object -Last 1
      if ($m) { $port = $m.Matches[0].Groups[1].Value }
    }
    if ($port) {
      try {
        $h = Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 5
        if ($h.status) {
          Say "healthy after $([int]((Get-Date)-$t).TotalSeconds)s on port $port"
          Say ("health: " + ($h | ConvertTo-Json -Compress -Depth 4))
          return [pscustomobject]@{ Process = $p; Port = $port; Health = $h; LogStart = $before }
        }
      } catch {}
    }
  }
  Show-LauncherLog $data $before
  Fail "no healthy backend within $budget s (port=$port)"
}

function Show-LauncherLog([string]$data, [int]$skip = 0) {
  $ll = Join-Path $data 'desktop-launcher.log'
  if (Test-Path -LiteralPath $ll) {
    Say "--- launcher log tail ---"
    Get-Content -LiteralPath $ll | Select-Object -Skip $skip | Select-Object -Last 60 | ForEach-Object { Write-Host "  $_" }
  } else { Say "no launcher log at $ll" }
}

function Get-StartupErrors([string]$data, [int]$skip) {
  $ll = Join-Path $data 'desktop-launcher.log'
  if (-not (Test-Path -LiteralPath $ll)) { return @() }
  @(Get-Content -LiteralPath $ll | Select-Object -Skip $skip | Select-String -Pattern 'Traceback|FATAL|panic|ERROR|CRITICAL|0xC0000005|-1073741819' | ForEach-Object { $_.Line })
}

function Get-Token([int]$port, [string]$data) {
  $base = "http://127.0.0.1:$port/api/v1/users"
  foreach ($dir in @($data, (Join-Path $env:USERPROFILE '.openestimator'))) {
    $f = Join-Path $dir '.demo_credentials.json'
    if (Test-Path -LiteralPath $f) {
      $cred = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
      # The estimator owns ordinary project work; the demo admin is tried last.
      $props = @($cred.PSObject.Properties | Sort-Object { if ($_.Name -like 'estimator@*') { 0 } elseif ($_.Name -like 'demo@*') { 2 } else { 1 } })
      Say "demo accounts in ${f}: $(@($props | ForEach-Object Name) -join ', ')"
      foreach ($pr in $props) {
        try {
          $tok = Invoke-RestMethod "$base/auth/login/" -Method Post -ContentType 'application/json' -Body (@{ email = $pr.Name; password = $pr.Value } | ConvertTo-Json) -TimeoutSec 60
          Say "login as $($pr.Name) from $f"
          return $tok.access_token
        } catch { Say "login $($pr.Name) refused: $($_.Exception.Message)" }
      }
    }
  }
  $email = 'installer.check@datadrivenconstruction.io'
  $pw = 'Installer-Check-2026!x'
  try {
    Invoke-RestMethod "$base/auth/register/" -Method Post -ContentType 'application/json' -Body (@{ email = $email; password = $pw; full_name = 'Installer Check' } | ConvertTo-Json) -TimeoutSec 60 | Out-Null
    Say "registered $email"
  } catch { Say "register: $($_.Exception.Message)" }
  $tok = Invoke-RestMethod "$base/auth/login/" -Method Post -ContentType 'application/json' -Body (@{ email = $email; password = $pw } | ConvertTo-Json) -TimeoutSec 60
  Say "login as $email"
  return $tok.access_token
}

function Invoke-Api([int]$port, [string]$token, [string]$method, [string]$path, $body = $null) {
  $p = @{ Uri = "http://127.0.0.1:$port$path"; Method = $method; Headers = @{ Authorization = "Bearer $token" }; TimeoutSec = 120 }
  if ($null -ne $body) { $p.ContentType = 'application/json'; $p.Body = ($body | ConvertTo-Json -Depth 6) }
  Invoke-RestMethod @p
}

function New-ProbeData([int]$port, [string]$token, [string]$tag) {
  $proj = Invoke-Api $port $token Post '/api/v1/projects/' @{ name = "Upgrade probe $tag" }
  Say ("project create answered: " + ($proj | ConvertTo-Json -Compress -Depth 3).Substring(0, [Math]::Min(600, ($proj | ConvertTo-Json -Compress -Depth 3).Length)))
  try { $back = Invoke-Api $port $token Get "/api/v1/projects/$($proj.id)"; Say "project read back: $($back.name)" } catch { Say "project read back failed: $($_.ErrorDetails.Message) $($_.Exception.Message)" }
  $boq = Invoke-Api $port $token Post '/api/v1/boq/boqs/' @{ project_id = $proj.id; name = "Probe BOQ $tag"; description = 'installer upgrade check' }
  $pos = Invoke-Api $port $token Post "/api/v1/boq/boqs/$($boq.id)/positions/" @{ boq_id = $boq.id; ordinal = '01.001'; description = "Probe concrete C30/37 $tag"; unit = 'm3'; quantity = 12.5; unit_rate = '145.20' }
  Say "created project=$($proj.id) boq=$($boq.id) position=$($pos.id)"
  [pscustomobject]@{ project = "$($proj.id)"; boq = "$($boq.id)"; position = "$($pos.id)"; tag = $tag }
}

function Test-ProbeData([int]$port, [string]$token, $probe) {
  $proj = Invoke-Api $port $token Get "/api/v1/projects/$($probe.project)"
  if ($proj.name -ne "Upgrade probe $($probe.tag)") { Fail "project name after upgrade is '$($proj.name)'" }
  $boq = Invoke-Api $port $token Get "/api/v1/boq/boqs/$($probe.boq)"
  $text = $boq | ConvertTo-Json -Depth 8
  if ($text -notmatch [regex]::Escape($probe.position)) {
    $list = Invoke-Api $port $token Get "/api/v1/boq/boqs/$($probe.boq)/positions/"
    $text = $list | ConvertTo-Json -Depth 8
    if ($text -notmatch [regex]::Escape($probe.position)) { Fail 'the BOQ position did not survive the upgrade' }
  }
  if ($text -notmatch 'Probe concrete') { Fail 'the BOQ position text did not survive the upgrade' }
  Say "probe data intact: project, BOQ and position $($probe.position)"
}

function Stop-App($run, [string]$app) {
  $p = $run.Process
  $closed = $p.CloseMainWindow()
  Say "close window sent=$closed"
  if (-not $p.WaitForExit(120000)) {
    Say "launcher did not exit within 120s after close; stopping its own pid $($p.Id)"
    Stop-Process -Id $p.Id -Force
  }
  Say "launcher exit code $($p.ExitCode)"
  Start-Sleep 10
  $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) })
  Say "processes still running from ${app}: $($left.Count) $(@($left | ForEach-Object { "$($_.Name):$($_.ProcessId)" }) -join ',')"
  $pg = @(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'")
  Say "postgres.exe processes on the machine: $($pg.Count)"
  $listen = Get-NetTCPConnection -State Listen -LocalPort $run.Port -ErrorAction SilentlyContinue
  Say "port $($run.Port) still listening: $([bool]$listen)"
}

function Uninstall-App([string]$app) {
  $u = Join-Path $app 'uninstall.exe'
  if (-not (Test-Path -LiteralPath $u)) { Fail "no uninstaller at $u" }
  $t = Get-Date
  $p = Start-Process -FilePath $u -ArgumentList '/S' -PassThru -Wait
  Wait-Uninstallers
  Start-Sleep 10
  $rest = @(Get-ChildItem -LiteralPath $app -Recurse -Force -ErrorAction SilentlyContinue)
  Say "uninstall exit=$($p.ExitCode) seconds=$([int]((Get-Date)-$t).TotalSeconds) dir_exists=$(Test-Path -LiteralPath $app) leftover_entries=$($rest.Count)"
  $rest | Select-Object -First 20 | ForEach-Object { Say "  left: $($_.FullName)" }
  $k = Get-UninstallKey
  Say "uninstall key after: $(if ($k) { $k.DisplayVersion } else { 'gone' })"
  $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) })
  Say "processes from the install dir after uninstall: $($left.Count)"
  $lnk = @(Get-ChildItem "$env:ProgramData\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter '*OpenConstruction*' -ErrorAction SilentlyContinue)
  Say "start menu entries left: $($lnk.Count)"
  return [pscustomobject]@{ Exit = $p.ExitCode; Left = $rest.Count; Key = [bool]$k; Procs = $left.Count }
}

function Save-Logs([string]$data, [string]$name) {
  $dst = Join-Path $env:RUNNER_TEMP "oe-logs\$name"
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  foreach ($f in @('desktop-launcher.log')) { $s = Join-Path $data $f; if (Test-Path -LiteralPath $s) { Copy-Item -LiteralPath $s $dst } }
  $logs = Join-Path $data 'logs'
  if (Test-Path -LiteralPath $logs) { Copy-Item -LiteralPath $logs -Destination $dst -Recurse -Force }
  Get-ChildItem -LiteralPath $data -Filter '*.log' -ErrorAction SilentlyContinue | Copy-Item -Destination $dst -Force
}
