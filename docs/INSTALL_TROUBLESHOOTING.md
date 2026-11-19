# Installation help and troubleshooting

Also available in [Deutsch](INSTALL_TROUBLESHOOTING.de.md) and [Русский](INSTALL_TROUBLESHOOTING.ru.md).

This page is for you if Construction AI OS shows a warning or an error while you install or start it. Find the message you see, read what it means, and do what the third line says. Most cases take a minute to fix and none of them put your projects at risk.

For a normal installation without problems, see [Install Construction AI OS](desktop/INSTALL.md).

## Before anything else: the log files

When something goes wrong, the app writes what happened to a log file. If you write to us, attach these files. They help us find the cause on the first try.

| File | Where it is | What it holds |
|---|---|---|
| `desktop-launcher.log` | Windows: `C:\Users\<your name>\.openestimate\`<br>macOS and Linux: `~/.openestimate/` | Everything the desktop app did while starting. It stays in your home folder even when `OE_DATA_DIR` moves the data |
| `backend-crash.log` | the `logs` folder inside your data folder, which is the same `.openestimate` folder unless you set `OE_DATA_DIR` | Details of an unexpected stop. It moves with `OE_DATA_DIR` |
| database `log` folder | `pgdata\log` inside your data folder, so `.openestimate\pgdata\log` by default. If `pgdata.location` exists in `.openestimate`, the `log` folder inside the folder it names | Why the built-in database did not start |
| `OpenConstructionERP-install-error.log` | Windows: `%TEMP%` (type `%TEMP%` into the Explorer address bar) | Why the installer refused to install |

The `.openestimate` folder is hidden on macOS and Linux. On a Mac, press Cmd+Shift+. in Finder to show hidden folders.

If you installed with pip, run `openconstructionerp doctor` in a terminal. It checks the usual problems, such as a busy port or a missing database, and prints what to do about each one.

## Windows: while installing

**You see:** a blue window "Windows protected your PC".
**It means:** the installer is not code signed yet, so Windows does not know the publisher. It is a warning, not a virus finding.
**Do:** click **More info**, check that the file name starts with `Construction AI OS`, then click **Run anyway**. Details and a way to check the download are in [Windows blocks the app](desktop/WINDOWS_BLOCKED.md).

**You see:** Smart App Control says it blocked the app, or the app ran once and is blocked on every start since.
**It means:** Windows 11 Smart App Control refuses unsigned programs and offers no button to continue.
**Do:** follow [Windows blocks the app](desktop/WINDOWS_BLOCKED.md). It explains how to tell which feature blocked the app and how to run it with Docker or WSL while Smart App Control stays on.

**You see:** "Please choose an installation folder whose path uses only Latin letters, digits and spaces. The built-in database cannot start from a folder with other characters in its path".
**It means:** the folder you picked has letters such as Cyrillic, Chinese or accented ones in its path. The built-in database cannot start from such a folder.
**Do:** keep the suggested folder `C:\Program Files\Construction AI OS`, or pick one like `C:\Construction AI OS`. In a silent installation (`/S`) the installer shows the same message, exits with code 3 and writes the reason to `%TEMP%\OpenConstructionERP-install-error.log`.

**You see:** the installer stops with an error about WebView2.
**It means:** Windows could not install Microsoft WebView2, the component that draws the app window. The installer carries it, so no internet connection is needed; the failure comes from Windows itself, for example a policy, a pending update or a damaged earlier WebView2.
**Do:** restart the computer and run the installer again. If it fails again, install "Microsoft Edge WebView2 Runtime" from the Microsoft website and then run our installer once more.

**You see:** your antivirus deletes or quarantines a file during the installation.
**It means:** the program is new and unsigned, so some antivirus products treat it with suspicion.
**Do:** check the download as described in [Windows blocks the app](desktop/WINDOWS_BLOCKED.md). If the check says `True`, restore the file from quarantine and allow the folder `C:\Program Files\Construction AI OS` in your antivirus. If you are not sure, write to us before you allow anything.

## Windows: upgrading to a new version

**You see:** a screen asking whether to write over the installed version or to remove it first, with a line above that suggests removing it.
**It means:** that line comes from the installer toolkit and we cannot change it.
**Do:** keep the option that is already selected (write over it). The installer closes the running app for you and keeps all your projects. The first start after an upgrade can take longer while the database updates itself.

**You see:** you also run Construction AI OS with pip or from a terminal on the same computer.
**It means:** both use the same `.openestimate` folder and the same database. The installer stops that database to replace the program files, which cuts off the terminal version. When you upgrade from 18.4.0, the old uninstaller also closes any program named `openconstructionerp.exe`, which includes a terminal version started with pip.
**Do:** stop the terminal version (Ctrl+C in its window) before you install or upgrade, and start it again afterwards.

**You see:** the old version's uninstall window appears in the middle of an upgrade.
**It means:** you chose to remove the old version first. That works, it only takes longer.
**Do:** let it finish. If it offers "Delete the application data", you can leave it unticked. It removes only what the app window keeps, your sign-in and your language choice (in `%APPDATA%` and `%LOCALAPPDATA%\io.openconstructionerp.desktop`), and never your projects.

## Desktop app: while starting

**You see:** the loading screen for a minute or more on the very first start.
**It means:** the app is creating its local database. This takes a minute or two once, and longer on a slow disk.
**Do:** wait and do not close the window. Later starts are fast.

**You see:** a box "Construction AI OS failed to start" that names a log file.
**It means:** the app could not open its window at all.
**Do:** start it once more. If the box comes back, send us the log file it names.

**You see:** "The backend started, but the local database is not answering, so the app cannot open."
**It means:** the local database did not come up, often because a previous run did not close cleanly.
**Do:** restart the computer and start the app again. If it repeats, send us `desktop-launcher.log`.

**You see:** "The backend started, but this installation is missing the application files it serves".
**It means:** part of the program folder is missing, usually removed by antivirus.
**Do:** check your antivirus quarantine, then run the installer again over the existing installation. Your projects are not touched.

**You see:** "The application backend did not start in time", or "The application backend stopped responding while preparing the local database" (or another step).
**It means:** the start took longer than the app waits. The message names the step it was on.
**Do:** close the window and start again. On a slow or nearly full disk, free some space first. If it stops at the same step again, send us `desktop-launcher.log`.

**You see:** "The drive ran out of space while the application was starting" or "There is not enough free space to start the application".
**It means:** exactly that. The message names the folder and how much space is left on its drive.
**Do:** free space on that drive and start the app again.

**You see:** a message that the folder for the local database "sits too deep in the filesystem", with two numbers in characters.
**It means:** Windows limits how long a full file path may be, and your data folder path is too long for the database files inside it. Reinstalling into the same place will not help, and switching on long paths in Windows does not help either.
**Do:** use a shorter data folder. Set the user environment variable `OE_DATA_DIR` to a short path such as `C:\cao-data` (Start, type "environment variables", "Edit environment variables for your account", New), then start the app again. If you run it from a terminal, use `openconstructionerp serve --data-dir C:\cao-data`.

**You see:** your Windows user name has non-Latin letters (for example Cyrillic or Chinese), and you look for your database.
**It means:** the database cannot work from such a path, so the app keeps it in `C:\ProgramData\OpenConstructionERP\clusters\<id>\pgdata`. The file `pgdata.location` in your `.openestimate` folder names the exact folder.
**Do:** nothing to fix. For backups, copy both `.openestimate` and the folder named in `pgdata.location`.

**You see:** "The application backend stopped, restarting" and the window reloads.
**It means:** the background part of the app stopped unexpectedly and the app restarted it. Your saved work is kept. It does this at most twice in 30 minutes.
**Do:** carry on. If it happens again and again, or you then see "The application backend has stopped", send us `desktop-launcher.log` and `logs\backend-crash.log`.

**You see:** every time you start the app you are signed out and the language is back to English.
**It means:** another program holds port 8732, the port the app normally uses. Version 18.5.0 then picks a random free port on each start, and the app window treats every new port as a new site, so it does not find your sign-in and language. Your projects are not affected.
**Do:** close or reconfigure the other program that uses port 8732. On Windows, `netstat -ano | findstr :8732` in a terminal shows its process ID, and Task Manager lists that ID under Details.

**You see:** "The application never finished unpacking itself, so its backend never started." or "The application could not unpack itself into the temporary folder it uses."
**It means:** on macOS and Linux the app unpacks its backend into a temporary folder on every start, as the Windows app did up to 18.4. A slow or full drive, or antivirus that removes or locks the files, stops that. From 18.5 the Windows app no longer unpacks itself.
**Do:** free space on that drive, or allow the app in your antivirus, then start again.

**You see:** you already run PostgreSQL on port 5432 and worry that the app conflicts with it.
**It means:** it does not. The built-in database takes a random free local port on Windows and listens only on a local socket on macOS and Linux.
**Do:** nothing.

## macOS

**You see:** the app does not run on your Mac at all.
**It means:** the Mac build is for Apple Silicon (M1 and later) only. There is no build for Intel Macs.
**Do:** on an Intel Mac, use pip or Docker as described in the README.

**You see:** "Construction AI OS is damaged and can't be opened", or "cannot be opened because the developer cannot be verified".
**It means:** the app is not notarized by Apple yet, and macOS blocks downloaded apps it cannot check. The app is not damaged.
**Do:** open Terminal and run once:

```
xattr -dr com.apple.quarantine "/Applications/Construction AI OS.app"
```

Or right-click the app in Applications and choose **Open**. On recent macOS go to **System Settings**, **Privacy & Security**, scroll down and click **Open Anyway**. You need to do this only once.

## Linux

**You see:** the `.deb` asks for `libwebkit2gtk-4.1-0` or refuses to install.
**It means:** the app needs the WebKitGTK 4.1 library to draw its window.
**Do:** install it with `sudo apt install ./construction-ai-os_*_amd64.deb`, which pulls the library in. If your distribution has no `libwebkit2gtk-4.1-0` (Ubuntu older than 22.04, Debian older than 12), use pip.

**You see:** the `.rpm` refuses to install or reports missing dependencies.
**It means:** `rpm -i` does not install the libraries the app needs.
**Do:** install with `sudo dnf install ./construction-ai-os-*.x86_64.rpm`, which pulls them in.

**You see:** the AppImage does nothing when you double-click it.
**It means:** the file is not marked as a program yet.
**Do:** run `chmod +x "Construction AI OS"*.AppImage` and start it again.

**You see:** an AppImage error that mentions FUSE or `libfuse.so.2`.
**It means:** newer distributions no longer install the FUSE 2 library that AppImages use.
**Do:** install it, for example `sudo apt install libfuse2` (on Ubuntu 24.04 the package is `libfuse2t64`), or use the `.deb`, `.rpm` or pip instead.

**You see:** a release has no AppImage.
**It means:** the AppImage is built separately and occasionally fails while the other files are fine.
**Do:** use the `.deb` or `.rpm` from the same release.

## pip (any system)

**You see:** pip says no matching version was found, or that Python is too old.
**It means:** Construction AI OS needs Python 3.12 or newer.
**Do:** install Python 3.12 or newer and run `python3.12 -m pip install --upgrade openconstructionerp` (on Windows `py -3.12 -m pip ...`).

**You see:** `error: externally-managed-environment` (Ubuntu 23.04 and newer, Debian 12 and newer).
**It means:** the system Python does not let pip install into it.
**Do:** use `pipx install openconstructionerp`, or create a virtual environment first: `python3 -m venv ~/oe && ~/oe/bin/pip install openconstructionerp`. [Installing on Linux](INSTALL_LINUX.md) has the details.

**You see:** `openconstructionerp` is not recognized, or command not found.
**It means:** the folder where pip puts commands is not on your PATH, which is common on Windows.
**Do:** run `python -m openconstructionerp` instead. It works on every system without touching PATH.

**You see:** "Port 8080 is already in use. Try: openconstructionerp serve --port 8081".
**It means:** another program uses port 8080.
**Do:** run the command it suggests and open the address it prints.

**You see:** "Embedded PostgreSQL could not start".
**It means:** the built-in database failed to start. The message names the folder with its log.
**Do:** run `openconstructionerp doctor`. If that does not help, reinstall with `pip install --upgrade --force-reinstall openconstructionerp` and send us the log it names.

**You see:** you are not sure where your data is.
**It means:** pip keeps everything in `.openestimate` in your home folder, the same folder the desktop app uses.
**Do:** to keep it elsewhere, start with `openconstructionerp serve --data-dir <folder>` or set `OE_DATA_DIR`.

## Docker

**You see:** Compose stops with "POSTGRES_PASSWORD must be set" or "JWT_SECRET must be set".
**It means:** the `.env` file with the two secrets is missing, or it is not in the folder with `docker-compose.yml`.
**Do:** create it as shown in [Getting started](getting-started.md#path-c-docker), in that folder. On Windows use the PowerShell commands given there, since a plain `>` in Windows PowerShell writes a file Compose cannot read.

**You see:** http://localhost:8080 does not open.
**It means:** the container is not running, or another program uses port 8080.
**Do:** run `docker compose ps` in the folder with `docker-compose.yml` and `docker compose logs app` to see why. To use another port, start with `OE_PORT=8081 OE_ALLOWED_ORIGINS=http://localhost:8081 docker compose up -d` and open http://localhost:8081. Keep the `.env` file in that folder safe: it holds the database password and the sign-in secret.

**You see:** on an Apple Silicon Mac or another ARM machine, Docker warns that the image platform `linux/amd64` does not match, or the app is very slow.
**It means:** the published image is built for x86-64 only.
**Do:** build from source with `make quickstart`, or use pip.

## Signing in to an installation you run yourself

**You see:** "Invalid email or password" on an account you just created, and creating it again says "Email already registered".
**It means:** the account exists and is waiting for an administrator to activate it. Installations default to `OE_REGISTRATION_MODE=admin-approve`, which stores every account but the very first one on an empty database as inactive. The first account on a genuinely empty database is activated automatically and becomes the administrator; if one is not, something was already in the database - a demo seed, an account from an earlier run, or a data folder the server is still reading.
**Do:** pick one of these.

- You run the installation yourself and want accounts to work as soon as they are created: start the server with the environment variable `OE_REGISTRATION_MODE` set to `open`. In Windows PowerShell run `$env:OE_REGISTRATION_MODE="open"` on the line before the one that starts it; in a Linux or macOS shell, export it the same way first. Under Docker, add `OE_REGISTRATION_MODE=open` to the `.env` file in the folder with `docker-compose.yml`, which is the file Compose reads. A `.env` file inside your data folder is not read: the one the program looks for sits next to the installed package, which for a pip install is inside your Python environment, so setting the variable in the environment you start from is the way that works everywhere.
- You are the administrator and want to activate one account: sign in as an administrator, open **Users** in the sidebar (the **User Management** page) and press **Activate** on that row. The team panel under Settings shows who is waiting but does not carry the switch; it links here.
- No administrator can sign in either: use the recovery commands below. They work offline, against the data folder, with no server running and no mail delivered.

**You see:** you cannot sign in and you no longer know the password, and there is no mail server to send a reset link.
**It means:** nothing is wrong with the installation; the password is simply not recoverable, because only its hash is stored.
**Do:** set a new one from a terminal, in the same environment you start the server from:

```
openconstructionerp reset-password you@example.com
```

It asks for the new password twice and echoes nothing while you type. It works on a stopped or a running server, and it activates the account if it was inactive, so you are not handed a correct password and a sign-in that still refuses. Add `--data-dir <folder>` if your data lives somewhere other than the default. If a script has to do it, `--password <password>` exists, but a password given that way is visible in the process list and in the shell's history, so the prompt is the better default.

The same command is available without PATH set up, as `python -m openconstructionerp reset-password you@example.com`.

**You see:** the last administrator left, or was deactivated, and nobody can reach **User Management**.
**It means:** the installation has no active administrator, so there is nobody who can activate or promote anybody.
**Do:** restore one from a terminal:

```
openconstructionerp promote-admin you@example.com
```

It makes that account an administrator and activates it, and it refuses an address that does not exist rather than creating one. Use `reset-password` afterwards if you also need a new password.

**You see:** "Password must be 72 bytes or fewer when encoded as UTF-8" while creating an account or setting a new password.
**It means:** the password is longer than the hash it is stored in can hold. Letters outside ASCII - accented, Cyrillic, Arabic, Chinese - take two or three bytes each, so a password of 30 such characters is over the limit even though it looks short.
**Do:** shorten it. Nothing was stored, so the account or the password is unchanged. Internal spaces are fine; spaces at the two ends are not part of a password here, and are removed before it is checked and before it is stored, so a password pasted with a space at the end still signs in.

## Running the server yourself: the first start

**You see:** the browser says it cannot reach the page, for a minute or two after you started the server.
**It means:** the port does not open until the first start has finished its work - creating the database schema, loading the modules, building the route table. Until then nothing is listening, so the browser is not being slow and the server is not refusing you: it has not reached the point where it can answer at all. A start that does all of it reaches an open port in about 143 seconds on a quiet machine, and the longest single phase measured inside that is the route table, at 32 seconds on a quiet machine and 59 seconds on a busy one. In the test suite that runs on every commit, the whole sequence - start, wait for health, register, sign in - took 58 seconds on Linux, 59 on macOS and 106 on Windows. A first start on an empty data folder is the slowest start you will ever see; every start after it reuses that work and opens in seconds.
**Do:** leave the terminal window open and read it instead of reloading the browser. A healthy start prints a line per phase as it reaches it, and while a phase takes a while it prints `Still working: <phase> (<seconds>s)` every fifteen seconds, so a window that is printing is a start that is progressing. When it is ready it prints the address to open. Two things mean something is genuinely wrong: no new line for four minutes, which is the interval the desktop launcher itself uses to decide a start has stopped, and a line containing `Traceback`. If you see either, put the last twenty lines of that window into a report along with the log files from the top of this page.

**You see:** the page opens and at once shows a message that data could not be loaded, or the sign-in page says it is still preparing your workspace.
**It means:** the page reached the server while the server was still starting, which on a first start is the normal order of events and not a fault. The interface asks whether the server is ready, waits, and asks again on a schedule that backs off - three seconds, then six, then twelve, then twenty-four, then half a minute at a time. After about two and a half minutes it stops asking, says the server is still starting, and puts a **Retry** button on the page, because a page that quietly polls forever looks exactly like a page that has given up. A message reading "Still starting up" is the same judgement about one request: the server answered 503, which is what it answers while it comes up.
**Do:** press **Retry** when you see it, or wait for the terminal window to print the address and then reload once. If the message comes back on every page long after the start finished, the server is not what is being waited for: run `openconstructionerp doctor` and read what it says about the port and the database.

**You see:** you pulled a newer version with `git pull`, restarted, and every page looks exactly as it did before.
**It means:** the server does not serve the interface from the files you pulled. It serves a copy that was built earlier - from `backend/app/_frontend_dist` when that folder exists, and from `frontend/dist` beside the package otherwise - and `git pull` fetches source without building anything. Your browser adds a second layer: a service worker keeps serving the copy it cached, so even a rebuilt folder can look unchanged until that cache is cleared.
**Do:** rebuild the interface, then clear the browser's copy of it. In Windows PowerShell, from the repository folder:

```
cd frontend
$env:NODE_OPTIONS="--max-old-space-size=8192"
npm ci
npm run build
```

On Linux or macOS the same four lines, with `export NODE_OPTIONS=--max-old-space-size=8192` in place of the second. The variable raises the memory the build is allowed to use; without it a build on a machine with 8 GB or less can stop with `JavaScript heap out of memory`. If it stops that way even with the variable set, run `npx vite build` instead of `npm run build`: that produces the same bundle and skips the separate type check, which is the part that needs the most memory. Then in the browser open the developer tools (F12), go to **Application**, press **Unregister** on the service worker, press **Clear site data**, and reload with Ctrl+F5. To see which folder your server is actually reading, run this from the `backend` folder:

```
python -c "from app.cli_static import get_frontend_dir; print(get_frontend_dir())"
```

**You see:** you registered, and signing in answers "Invalid email or password", or says the account was created and an administrator has to activate it.
**It means:** the account exists and is not active yet. On an installation that is not brand new that is the default rather than a fault; the first account on a genuinely empty database is the exception, and is activated and made the administrator, because a new installation with no way in is not an installation.
**Do:** read [Signing in to an installation you run yourself](#signing-in-to-an-installation-you-run-yourself) above, which is where this section hands that case. It names the three ways out - opening registration with `OE_REGISTRATION_MODE`, activating the account as an administrator, and setting a new password from a terminal - what each of them costs, and the password rule the sign-up form states before you submit.

## Uninstalling and your data

Uninstalling removes the program and keeps your projects. They live in the `.openestimate` folder in your home folder (plus the `ProgramData` folder above, if your user name has non-Latin letters). Reinstalling therefore does not start you over. To start from scratch, uninstall and then delete `.openestimate` yourself, after you have copied it somewhere safe.

## Still stuck

Open an issue at [github.com/abdelnabym519-cpu/Construction-AI-OS/issues](https://github.com/abdelnabym519-cpu/Construction-AI-OS/issues). Please include:

- the version you installed and how (Windows installer, `.dmg`, `.deb`, `.rpm`, AppImage, pip or Docker),
- your system (Windows: Start, type `winver`; macOS: Apple menu, About This Mac),
- the exact text of the message, or a screenshot,
- the log files from the top of this page.
