# Autostart OpenConstructionERP on system boot

Three ready-to-use templates for the three major OSes. Pick yours.

| File | OS | Mechanism |
|---|---|---|
| `systemd-openestimate.service` | Linux | systemd unit (boot-level) |
| `macos-com.openestimate.plist` | macOS | launchd (login or boot) |
| `windows-install-service.ps1` | Windows | Task Scheduler (logon-level) |

All three start `openestimate serve` and rebind on crash.

---

## Linux — systemd

```bash
# 1. Install backend (creates ~/.venv with openestimate inside it)
sudo useradd -m -r -s /bin/bash openestimate
sudo -u openestimate python3 -m venv /home/openestimate/.venv
sudo -u openestimate /home/openestimate/.venv/bin/pip install --upgrade openconstructionerp

# 2. Drop the unit file in
sudo cp systemd-openestimate.service /etc/systemd/system/openestimate.service

# 3. Enable + start
sudo systemctl daemon-reload
sudo systemctl enable --now openestimate

# 4. Verify
sudo systemctl status openestimate
curl http://localhost:8000/api/health
```

Logs: `journalctl -u openestimate -f`

To expose to LAN, the unit already binds to `0.0.0.0`. Open the firewall:
```bash
sudo ufw allow 8000/tcp
```

---

## macOS — launchd

```bash
# 1. Install (in your venv of choice)
python3 -m venv ~/.venv
~/.venv/bin/pip install --upgrade openconstructionerp

# 2. Edit the plist — replace USERNAME with your home dir name
sed -i '' "s|USERNAME|$USER|g" macos-com.openestimate.plist

# 3. Drop into LaunchAgents (per-user, runs at login)
mkdir -p ~/.openestimate/logs ~/Library/LaunchAgents
cp macos-com.openestimate.plist ~/Library/LaunchAgents/

# 4. Load it
launchctl load -w ~/Library/LaunchAgents/com.openestimate.serve.plist

# 5. Verify
launchctl list | grep openestimate
curl http://localhost:8000/api/health
```

To unload: `launchctl unload ~/Library/LaunchAgents/com.openestimate.serve.plist`

For system-wide (boot, not login) — drop into `/Library/LaunchDaemons/` with
`sudo`, set `<key>UserName</key>` in the plist, and load with `sudo launchctl`.

---

## Windows — Task Scheduler

```powershell
# Open PowerShell as Administrator, navigate to this folder, then:
.\windows-install-service.ps1
```

The script edits the `$openestimatePath` and `$bindHost` at the top — adjust
those before running if you used a non-default install location.

Verify:
```powershell
schtasks /Query /TN OpenConstructionERP
curl http://localhost:8000/api/health
```

To remove:
```powershell
schtasks /Delete /TN OpenConstructionERP /F
```

For LAN access on Windows, also open the firewall:
```powershell
New-NetFirewallRule -DisplayName "OpenEstimate 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

---

## Network access — security checklist

If you bind to `0.0.0.0` (LAN-accessible):

- [ ] **Disable demo login**: `Environment=SEED_DEMO=false` (systemd) /
      `<key>SEED_DEMO</key><string>false</string>` (launchd) /
      `$env:SEED_DEMO="false"` before `Start-ScheduledTask`. Demo creds are
      published — they should never be reachable from a network you don't
      control.
- [ ] **Set ALLOWED_ORIGINS** to your real frontend URL, not `*`.
- [ ] **Put behind a reverse proxy** (Caddy / nginx) for HTTPS termination.
      Don't expose the FastAPI dev server directly to the public internet.
- [ ] **Use PostgreSQL**, not the bundled SQLite, if you have >1 user
      writing concurrently.
