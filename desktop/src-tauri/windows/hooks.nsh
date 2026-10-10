; OpenConstructionERP - NSIS installer hooks
;
; Windows keeps an exclusive lock on a running .exe. If the backend sidecar
; (openconstructionerp-server.exe) is still running when the installer tries to
; overwrite it, or when the uninstaller tries to delete it, the operation fails
; with "file in use by another process". That is the reinstall error users hit:
; after the app is closed or uninstalled the sidecar can linger in the
; background, and the next install cannot replace the locked file until the
; process is stopped by hand in Task Manager.
;
; These hooks stop that process before the installer writes files and before the
; uninstaller removes them, so the file lock is gone by the time it matters.
;
; Two things they must not do, and used to.
;
; They must not kill processes that are not ours to kill. The old hooks ran
; `taskkill /F /T /IM <name>`, and /IM matches by image name across the whole
; machine: an elevated installer stopped that image in EVERY logged-in user's
; session, and in every other installation of the product on the machine.
; Matching on the executable path instead scopes the stop to the installation
; being worked on. Another install, in another directory, is now none of our
; business - which it always was.
;
; And they must not force-kill when they can ask. A forced stop is an unclean
; stop for the embedded PostgreSQL cluster the backend runs, so the next start
; has a write-ahead log to replay, which on a large database takes minutes and
; is what users have been reading as "the application backend did not start in
; time" after an upgrade. Closing the app's window instead runs the launcher's
; own exit path, which asks the backend to shut down cleanly. So: ask first,
; wait, and force only what is left.
;
; The path comes through the environment rather than being pasted into the
; PowerShell command, so an install directory containing a quote or a dollar
; sign cannot break the script that is supposed to protect it.
;
; The taskkill lines are the fallback for a machine where PowerShell will not
; run at all. They are narrowed to this user's own processes, so they can never
; reach into another user's session the way the original did - and they run ONLY
; when PowerShell could not be started, because the USERNAME filter makes
; taskkill resolve the owner of every process on the machine, which was measured
; at 55 seconds per call. An installer may not spend two minutes on a step that
; usually has nothing to do.

; One more thing this has to get right, and it is invisible from the source: an
; NSIS installer is a 32-bit process, so `powershell` on its PATH resolves under
; WOW64 to the 32-bit copy in SysWOW64 - and a 32-bit process cannot read the
; module list of a 64-bit one, so `(Get-Process).Path` is empty for every
; process this hook cares about. Measured, not reasoned: with redirection left
; on, the filter matched 0 of 1 running processes and the hook was a silent
; no-op. Turning file-system redirection off for the call gets the 64-bit
; PowerShell, which matched 1 of 1.

; The path filter above cannot reach one process that matters, and it is the
; process with the most to lose. The embedded PostgreSQL postmaster is not
; started from $INSTDIR: it is executed out of the temporary directory the
; onefile backend bundle unpacks itself into, so its path is under %TEMP% and
; the filter never matches it. What that costs is in the bug report it came
; from: after the app is gone the postmaster is still running, still holding
; the data directory and still holding the port, so the next install starts
; against a cluster it does not own, and an uninstall leaves a process behind
; with nothing left on disk to explain it.
;
; It is not enough to look for an image called postgres.exe. A developer
; machine or a server may well be running an unrelated PostgreSQL, and killing
; someone else's database because it shares an image name is the same mistake
; the old /IM taskkill made, one layer down.
;
; So the postmaster is identified the way PostgreSQL itself identifies it: by
; the pid file it writes into its own data directory. Line 1 is the pid and
; line 3 is the start time in Unix seconds. Reading that file names exactly one
; process, and it is by construction the postmaster of OUR cluster.
;
; Two guards sit on top of it, because a pid file outlives the process that
; wrote it. A stale file names a pid Windows is free to hand to something else,
; so the process found under that pid must still be called postgres, and its
; start time must still be the one the file recorded. A recycled pid fails the
; second check even when it passes the first.
;
; The data directory is resolved through the same three environment variables,
; in the same order, that the backend itself uses (OE_DATA_DIR, then DATA_DIR,
; then OE_CLI_DATA_DIR, then ~/.openestimate). A test asserts that order
; against the backend's own resolver rather than against a copy of it, so the
; two cannot drift apart quietly.
;
; This runs after the window has been asked to close, not instead of it. In the
; ordinary case the launcher has already stopped the cluster cleanly by then and
; there is no pid file left to act on. This is the last resort, and a forced
; stop here is still better than the alternative it replaces, which was leaving
; the postmaster running forever.

; Every one of these calls is bounded, and the reason is a bug report rather
; than a principle. nsExec waits for the child forever unless it is given
; /TIMEOUT, and the uninstaller waits for nsExec, and the installer waits for
; the uninstaller. So a PowerShell that never returns - a wedged host, an
; antivirus holding the image, a console that never gets a handle - stops the
; upgrade dead on the line "Closing OpenConstructionERP..." with no way out but
; the task manager. That is exactly what a user saw. On expiry nsExec pushes
; the string "timeout" rather than an exit code, which the caller below already
; reads as "not zero" and answers with the by-name fallback, so a timed-out
; PowerShell degrades into the slower path instead of into a hang.
;
; The numbers are bounds, not budgets. The window close already waits up to 15
; seconds inside PowerShell, and PowerShell itself can take several seconds to
; start on a cold machine, so 60 seconds is the first point at which the call
; is certainly not working rather than merely slow. The postmaster stop has no
; internal wait and gets 30. The taskkill fallbacks get 90 each because the
; USERNAME filter makes taskkill resolve the owner of every process on the
; machine, which was measured at 55 seconds on an ordinary desktop.
;
; One thing this cannot fix, and it is worth writing down because it is not
; visible from here. On an upgrade the new installer runs the PREVIOUSLY
; INSTALLED uninstaller, from PageLeaveReinstall, which happens before
; NSIS_HOOK_PREINSTALL exists to run. So the hook that decides whether an
; upgrade hangs is the one that shipped in the version already on disk, never
; the one in the installer being run. Every fix here reaches the upgrade AFTER
; next, and there is no earlier hook point to borrow: the template defines four
; and all of them are later than this.

!include LogicLib.nsh
!include x64.nsh

!macro OE_STOP_OUR_POSTMASTER
  Push $0
  DetailPrint "Checking for a running database..."
  ${If} ${RunningX64}
    ${DisableX64FSRedirection}
  ${EndIf}
  nsExec::Exec /TIMEOUT=30000 `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$r = @($$env:OE_DATA_DIR,$$env:DATA_DIR,$$env:OE_CLI_DATA_DIR,(Join-Path $$env:USERPROFILE '.openestimate')) | Where-Object { $$_ } | Select-Object -First 1; $$d = Join-Path $$r 'pgdata'; $$m = Join-Path $$r 'pgdata.location'; if (Test-Path -LiteralPath $$m) { $$t = (Get-Content -LiteralPath $$m -Raw -Encoding UTF8).Trim(); if ($$t) { $$d = $$t } }; $$f = Join-Path $$d 'postmaster.pid'; if (Test-Path -LiteralPath $$f) { $$l = @(Get-Content -LiteralPath $$f -TotalCount 3); $$n = $$l[0] -as [int]; $$t = $$l[2] -as [int]; if ($$n) { $$p = Get-Process -Id $$n -ErrorAction SilentlyContinue; if ($$p -and $$p.ProcessName -eq 'postgres') { $$s = $$null; try { $$s = ([DateTimeOffset]$$p.StartTime).ToUnixTimeSeconds() } catch { }; if (-not $$t -or -not $$s -or [Math]::Abs($$s - $$t) -le 5) { Stop-Process -Id $$n -Force -ErrorAction SilentlyContinue } } } }"`
  Pop $0
  ${If} ${RunningX64}
    ${EnableX64FSRedirection}
  ${EndIf}
  Pop $0
!macroend

!macro OE_STOP_THIS_INSTALL
  Push $0
  DetailPrint "Closing OpenConstructionERP..."
  ; Hand the install directory to the script below without quoting it.
  System::Call 'kernel32::SetEnvironmentVariable(t "OE_STOP_DIR", t "$INSTDIR")'
  ; Close the app window (which stops its backend cleanly), give it a bounded
  ; wait, then force whatever is still running from this directory. The wait
  ; only happens if something actually had a window to close, so an orphaned
  ; backend with no app in front of it is dealt with immediately.
  ${If} ${RunningX64}
    ${DisableX64FSRedirection}
  ${EndIf}
  nsExec::Exec /TIMEOUT=60000 `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$d = $$env:OE_STOP_DIR; if ($$d) { $$p = @(Get-Process -ErrorAction SilentlyContinue | Where-Object -Property Path -Like ($$d + '\*')); if ($$p.Count -gt 0) { if (@($$p.CloseMainWindow()) -contains $$true) { $$p | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue }; $$p | Stop-Process -Force -ErrorAction SilentlyContinue } }"`
  Pop $0
  ${If} ${RunningX64}
    ${EnableX64FSRedirection}
  ${EndIf}
  ${If} $0 != "0"
    ; PowerShell could not be run at all ("error", or a non-zero exit). The
    ; former product name is here too, because an upgrade from it is the one
    ; case a path match can miss: that install may live in another directory.
    DetailPrint "Falling back to stopping the processes by name..."
    nsExec::Exec /TIMEOUT=90000 `cmd /c taskkill /F /T /FI "IMAGENAME eq openconstructionerp-server.exe" /FI "USERNAME eq %USERNAME%"`
    Pop $0
    nsExec::Exec /TIMEOUT=90000 `cmd /c taskkill /F /T /FI "IMAGENAME eq openestimate-server.exe" /FI "USERNAME eq %USERNAME%"`
    Pop $0
  ${EndIf}
  ; Whatever the app's own exit did or did not manage, the cluster must not be
  ; left running. In the normal case this finds nothing, because closing the
  ; window already stopped it cleanly.
  !insertmacro OE_STOP_OUR_POSTMASTER
  ; A moment for Windows to release the file handles after the exits.
  Sleep 800
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro OE_STOP_THIS_INSTALL
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro OE_STOP_THIS_INSTALL
!macroend

; Up to 18.4 the backend shipped as one onefile executable next to the
; launcher. It is now the onedir folder $INSTDIR\server, so a copy of the old
; file left by an upgrade is dead weight of about 650 MB. The uninstaller of
; the previous version normally removes it; this covers the case where it did
; not, for example a file held open at the time.
!macro NSIS_HOOK_POSTINSTALL
  Delete "$INSTDIR\openconstructionerp-server.exe"
!macroend

; The install directory has to be an ASCII path. Since the backend became a
; onedir folder, the bundled PostgreSQL runs from $INSTDIR\server itself, and
; its initdb cannot find its own postgres.exe when that path holds characters
; outside the ANSI code page: "could not re-execute with restricted token" and
; "program postgres is needed by initdb but was not found". The app then never
; starts. Up to 18.4 the binaries ran from an unpacked copy under the user's
; profile, so this is new with onedir. The data directory has its own ASCII
; fallback in the backend; the binaries cannot be moved from here, so the
; installer refuses the folder instead.
;
; The test is a round trip through the US-ASCII code page (20127): every
; character outside it comes back as "?", which a Windows path cannot contain,
; so a difference means the path is not ASCII. StrCmpS, because StrCmp ignores
; case and would call two different strings equal.
!define OE_NON_ASCII_INSTDIR_TEXT "Please choose an installation folder whose path uses only Latin letters, digits and spaces. The built-in database cannot start from a folder with other characters in its path:$\n$\n$INSTDIR"

; Leaves "1" on the stack when $INSTDIR is ASCII, "0" otherwise.
Function OE_InstDirIsAscii
  Push $0
  Push $1
  StrCpy $1 ""
  System::Call 'kernel32::WideCharToMultiByte(i 20127, i 0, w "$INSTDIR", i -1, m .r1, i ${NSIS_MAX_STRLEN}, p 0, p 0) i .r0'
  ${If} $0 = 0
    StrCpy $0 "0"
  ${Else}
    StrCmpS $1 $INSTDIR 0 +3
      StrCpy $0 "1"
      Goto +2
    StrCpy $0 "0"
  ${EndIf}
  Pop $1
  Exch $0
FunctionEnd

; Leave callback of the directory page: say why and stay on the page.
Function OE_CheckInstallDirectory
  Call OE_InstDirIsAscii
  Pop $0
  ${If} $0 != "1"
    MessageBox MB_OK|MB_ICONEXCLAMATION "${OE_NON_ASCII_INSTDIR_TEXT}"
    Abort
  ${EndIf}
FunctionEnd

; Before any file is written, for every mode: a silent install with /D= never
; sees the directory page. Exits non-zero, writes the reason to the console it
; was started from and to %TEMP%\OpenConstructionERP-install-error.log.
!macro OE_REFUSE_NON_ASCII_INSTDIR
  Call OE_InstDirIsAscii
  Pop $0
  ${If} $0 != "1"
    FileOpen $1 "$TEMP\OpenConstructionERP-install-error.log" w
    ${If} $1 != ""
      FileWriteUTF16LE /BOM $1 "${OE_NON_ASCII_INSTDIR_TEXT}$\r$\n"
      FileClose $1
    ${EndIf}
    System::Call 'kernel32::AttachConsole(i -1)i.r0'
    ${If} $0 <> 0
      System::Call 'kernel32::GetStdHandle(i -11)i.r0'
      FileWrite $0 "The install folder must be an ASCII path: $INSTDIR$\r$\n"
    ${EndIf}
    MessageBox MB_OK|MB_ICONEXCLAMATION "${OE_NON_ASCII_INSTDIR_TEXT}" /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
!macroend
