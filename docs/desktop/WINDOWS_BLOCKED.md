# Windows blocks the app (unknown publisher)

Also available in [Deutsch](WINDOWS_BLOCKED.de.md) and [Русский](WINDOWS_BLOCKED.ru.md).

For any other warning or error while installing or starting, see [Installation help](../INSTALL_TROUBLESHOOTING.md) (also [online](https://openconstructionerp.com/install-help)).

This page is for you if Windows refuses to start OpenConstructionERP, calls it an app from an unknown or unverified publisher, or let it run once and blocks it on every start since.

## Why this happens

The Windows builds of OpenConstructionERP are not code signed yet. A signature is how Windows learns who published a program, and without one Windows treats the app as coming from an unknown publisher. Two separate Windows features react to that, and they need different handling:

- **Microsoft Defender SmartScreen** shows a blue "Windows protected your PC" window when you start a program downloaded from the internet that Windows does not recognise yet. It warns, and it lets you continue.
- **Smart App Control** is a stricter feature of Windows 11. When it is on, it blocks every program file that Microsoft's cloud service cannot vouch for and that carries no trusted signature, and it offers no button to continue and no per-app exception. Its message names Smart App Control and usually says that the app, or part of it, has been blocked.

Smart App Control also explains the most confusing case, where the app ran once and is blocked on every later start. After a clean Windows install, Smart App Control starts in an evaluation mode, in which it only watches and blocks nothing. Later Windows decides whether to switch it on or off for good, and when it switches on, a program that worked yesterday is blocked today although nothing changed on our side. The desktop app also unpacks a few hundred helper files (the embedded PostgreSQL database among them) every time it starts, and Smart App Control checks each of them, not only the file you downloaded.

The name in the notification can be confusing. The block comes from the Windows Security app, whatever the popup looks like, so the next step is to find out which feature did it.

## Step 1: find out what blocked it

1. Open **Start**, type **Windows Security** and open it.
2. Go to **Virus & threat protection**, then **Protection history**.
3. Look at the newest entries. An entry that mentions **Smart App Control** or **Blocked app** means Smart App Control. An entry about a detected threat means Microsoft Defender Antivirus.

Then check whether Smart App Control is on: in Windows Security go to **App & browser control** and open **Smart App Control settings**. It shows **On**, **Evaluation** or **Off**.

To see exactly which file was refused, open **Event Viewer**, go to **Applications and Services Logs** > **Microsoft** > **Windows** > **CodeIntegrity** > **Operational**, and look for event **3077**. For the desktop app the file usually sits under `%LOCALAPPDATA%\OpenConstructionERP\extract`, where the app unpacks its helper files on every start. That block is expected for an unsigned build and does not mean the file is a virus.

## Step 2a: SmartScreen ("Windows protected your PC")

This one is safe to get past once you are sure the file is ours (see "Check that the download is genuine" below).

1. In the "Windows protected your PC" window, click **More info**.
2. Check the file name, then click **Run anyway**.

SmartScreen only asks for files downloaded from the internet. If it keeps asking for the same installer, you can also right-click the downloaded `.exe`, choose **Properties**, tick **Unblock** at the bottom of the **General** tab, and click **OK**. That removes the "downloaded from the internet" mark from this one file. It has no effect on Smart App Control, which checks every program file wherever it came from.

## Step 2b: Smart App Control is on

There is no way to allow a single app while Smart App Control stays on. Microsoft's own advice is to turn it off or to ask the publisher to sign the app, and our Windows builds are not signed today. That leaves two honest choices.

**Option 1: keep Smart App Control on and run the app another way.** This is what we recommend if you want to keep the protection. Docker and WSL both run OpenConstructionERP inside a small Linux environment, and Smart App Control does not check Linux programs. Both are described below.

**Option 2: turn Smart App Control off.** This lowers the protection of your whole PC, not only for our app, so do it only if you are comfortable with that. On current Windows 11 builds you can switch it back on later from the same page, but on older builds turning it off is permanent until you reset or reinstall Windows. If the page offers no way back on after you turn it off, you are on such a build.

1. Open **Windows Security**, go to **App & browser control**, then **Smart App Control settings**.
2. Select **Off** and confirm.
3. Start OpenConstructionERP again.

Microsoft Defender Antivirus and SmartScreen stay on either way.

If Protection history shows a Microsoft Defender Antivirus detection instead, and you have checked the file as described below, you can open that entry and choose **Actions**, then **Allow on device**. If you are unsure, do not allow it and write to us instead.

## Run it with Docker (works with Smart App Control on)

1. Install **Docker Desktop** from docker.com and start it once. Docker Desktop is free for personal use, education, and small companies; larger companies need a paid Docker subscription.
2. Create a folder, for example `C:\OpenConstructionERP`, open **Windows PowerShell** in it, and run:

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.yml -o docker-compose.yml
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.image.yml -o docker-compose.override.yml
function New-Secret([int]$n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }
Set-Content -Path .env -Encoding ascii -Value @("POSTGRES_PASSWORD=$(New-Secret 24)", "JWT_SECRET=$(New-Secret 32)")
docker compose pull app
docker compose up -d
```

3. Open **http://localhost:8080** in your browser and sign in with `demo@openconstructionerp.com` / `DemoPass1234!`.

The `.env` file holds the database password and the login secret, so keep it. Next time only `docker compose up -d` in the same folder is needed.

## Run it in WSL (works with Smart App Control on)

WSL is Microsoft's built-in Linux environment for Windows.

1. Open **Windows PowerShell as administrator**, run `wsl --install`, and restart the PC when asked. On first start Ubuntu asks you to choose a user name and password.
2. In the **Ubuntu** window, run:

```bash
sudo apt update && sudo apt install -y python3-venv
python3 -m venv ~/openconstructionerp
~/openconstructionerp/bin/pip install --upgrade openconstructionerp
~/openconstructionerp/bin/openconstructionerp
```

3. Open **http://localhost:8080** in your Windows browser. The first start takes a minute or two while the database is set up. Next time open Ubuntu and run only the last line.

## Run it with pip on Windows (only with Smart App Control off)

If Smart App Control is off or never switched on, but you would rather not use the installer, you can run the app directly with Python. Do not rely on this route as a way around Smart App Control: the app starts its own PostgreSQL database, whose program files are not signed either, so with Smart App Control on the database is blocked in the same way.

1. Download Python 3.12 from [python.org/downloads/windows](https://www.python.org/downloads/windows/) and run the installer. On its first screen tick **Add python.exe to PATH**, then click **Install Now**.
2. Open a new **Windows PowerShell** window and run:

```powershell
py -3.12 -m pip install --upgrade openconstructionerp
py -3.12 -m openconstructionerp
```

3. The first run sets up the local database and loads demo data, which takes about a minute. The app then runs at **http://localhost:8080**; sign in with `demo@openconstructionerp.com` / `DemoPass1234!`. Next time only the second command is needed.

## Check that the download is genuine

Every release lists a `SHA256SUMS` file next to the installers. Download it into the same folder as the installer, open **Windows PowerShell** in that folder, and run:

```powershell
$exe = Get-ChildItem OpenConstructionERP_*_x64-setup.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$line = Select-String -Path SHA256SUMS -Pattern $exe.Name -SimpleMatch
(Get-FileHash $exe.FullName -Algorithm SHA256).Hash -eq $line.Line.Split(' ')[0]
```

`True` means the file is exactly the one our release build produced. `False` means it was damaged or changed on the way, so do not run it. A red error instead of `True` or `False` means the folder holds a `SHA256SUMS` from a different release than the installer, so download both from the same release page. If `False` persists, download it again from the [GitHub release page](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest). The check proves the file is intact. It does not change what SmartScreen or Smart App Control decide. For a stronger check, `SHA256SUMS` itself carries a Sigstore signature, described in [RELEASE_SIGNATURE_INVENTORY.md](RELEASE_SIGNATURE_INVENTORY.md).

## Still stuck

Write to info@datadrivenconstruction.io or open an issue on GitHub. Tell us your Windows version (Start, type `winver`), what the Smart App Control settings page shows, and the exact text of the message.

## Sources

- Microsoft Learn, [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- Microsoft Learn, [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- Microsoft Support, [Smart App Control frequently asked questions](https://support.microsoft.com/en-us/windows/smart-app-control-frequently-asked-questions-285ea03d-fa88-4d56-882e-6698afdb7003)
- Microsoft Support, [Smart App Control has blocked part of this app](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-has-blocked-part-of-this-app)
- Microsoft Support, [App & browser control in the Windows Security app](https://support.microsoft.com/en-us/windows/security/windows-security/app-browser-control-in-the-windows-security-app)
