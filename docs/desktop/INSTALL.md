# Install OpenConstructionERP

OpenConstructionERP by DataDrivenConstruction is an open-source platform for construction cost estimation, bills of quantities, and data validation, with CAD and BIM quantity takeoff and multi-currency support. The desktop app puts the whole thing on your computer. You download one installer and run it. There is no Python, no pip, no Docker, and no database to set up. Everything it needs is already inside.

This guide walks you through installing it and signing in for the first time.

## Where to download

The installers live on the project's GitHub Releases page. Open the latest release and pick the file that matches your computer. Windows gets a `.exe`, macOS gets a `.dmg`, and Linux gets either a `.deb` or an `.AppImage`. Each release is built automatically and the files are attached right there. The macOS build is for Apple Silicon (M1 and later) only; there is no build for Intel Macs, so on an Intel Mac use the pip or Docker route from the README instead.

## Download and install

### Windows

Each release attaches one Windows installer, an `.exe`. It installs for all users of the machine, into `C:\Program Files\OpenConstructionERP`, so Windows asks for administrator permission before it continues. Releases up to 15.1.0 also carried an `.msi`. It installed the same application to the same place but kept its own record of having done so, which is why two installers for one program was a trap rather than a choice, and from 15.2.0 it is gone. If the copy you have came from the `.msi`, uninstall that entry before you run the `.exe`, otherwise the machine lists the app twice. Your data is not in the installed folder and an uninstall does not touch it.

The app needs Microsoft's WebView2 runtime. If your machine does not already have it the installer fetches it during installation, so there is nothing extra to install by hand, but it does mean that a first install on a machine without WebView2 needs a working internet connection. Without one the installer stops and reports that WebView2 could not be installed. Once WebView2 is present, installing and running the app work offline.

When it finishes you will find OpenConstructionERP in the Start Menu and as a shortcut, both named "OpenConstructionERP". Click either one to launch it.

### macOS

Download the `.dmg`, open it, and drag OpenConstructionERP into your Applications folder. You need a Mac with Apple Silicon, since the `.dmg` will not start on an Intel Mac.

This build is ad-hoc signed but not yet notarized by Apple, so the first time you open it macOS may say it "is damaged and can't be opened" or otherwise block it. The app is not damaged. macOS quarantines anything downloaded from the web, and an app that Apple has not notarized trips that check. To clear it, open Terminal and run this once, then open the app normally:

```
xattr -dr com.apple.quarantine /Applications/OpenConstructionERP.app
```

On older macOS you can instead right-click the app and choose Open. On macOS Sequoia you may also need to approve it once under System Settings, in Privacy and Security, where macOS shows a button to open the app anyway. You only need to do this once.

### Linux

On Debian or Ubuntu, download the `.deb` and install it with your package manager. It depends on `libwebkit2gtk-4.1-0`, which your system will pull in if it is not already present. After that, launch OpenConstructionERP from your applications menu.

If you prefer something portable, download the `.AppImage` instead, make it executable, and run it. From a terminal that is:

```
chmod +x OpenConstructionERP*.AppImage
./OpenConstructionERP*.AppImage
```

## First launch

The very first time you open the app it sets up its local database, and that takes a little while, usually somewhere between 40 and 90 seconds. While it works you will see a branded loading screen telling you the setup is in progress. This is normal and it only happens once. Please let it finish without closing the window. Every launch after this one starts quickly.

## Sign in

Once the app is ready you will reach the sign-in screen. A demo account is ready to go so you can look around right away.

Email: demo@openconstructionerp.com
Password: DemoPass1234!

Sign in with those and you are in. You can create your own account and projects from there.

## Your data is local

Everything you do stays on your own machine. The app runs its own database locally and does not send your projects anywhere. It works offline, and your data is yours.

All of it lives in a single folder in your home directory, named `.openestimate`. On Windows that is `C:\Users\<your name>\.openestimate`, and on macOS and Linux it is `~/.openestimate`. That folder holds the local PostgreSQL database, every file you have uploaded, and your settings. It sits outside the program folder on purpose, so that installing, upgrading and removing the app never touch your work. To make a backup, close the app and copy that folder somewhere safe.

## Upgrading to a new version

Close the app before you start. On Windows, download the new installer and run it. It notices the version you already have and offers either to write the new files over it or to remove it first. Writing over it is the option already selected for you, and it is the one to take: the installer stops anything of the old version that is still running and then replaces the program files where they are. Above the two options that screen also carries a line of its own that still suggests removing the current version first. That line comes from the toolkit the installer is built with and we cannot change it, so go by the option that is already selected rather than by the sentence above it. Your `.openestimate` folder is not part of the upgrade, so your projects, users and settings are all still there when the new version starts. The first start after an upgrade can take longer than usual while the database brings itself up to date, and that is normal.

Removing the old version first is still offered and still works, and if you pick it, Windows shows you the old version's own uninstall window in the middle of the upgrade. That looks alarming but is only the old program files being cleared out, and it takes longer than writing over them. If that window offers a checkbox called "Delete the application data", you can leave it alone. It does not remove your projects, and what it does remove is described in the next section.

Installing an older version over a newer one is only possible if you let the installer remove the newer one first. On macOS, drag the new app into Applications and replace the old one. On Linux, install the new `.deb` over the old one, or replace the `.AppImage` file.

## Uninstalling

Remove OpenConstructionERP the way you remove any other program, from Windows Settings under installed apps, by dragging it out of Applications on macOS, or with your package manager on Linux. Close the app first so that nothing of it is still running.

Uninstalling removes the program and leaves your data where it is. The `.openestimate` folder survives with the database and every uploaded file in it, which is what you want when you are reinstalling or moving to a newer version, and it is also why reinstalling is not a way to start over. If you installed with the `.exe`, its uninstaller offers a checkbox called "Delete the application data", and despite the name it does not touch `.openestimate` either. All it targets is the small folder the app keeps for its built-in browser view, which holds the sign-in session and the window state and nothing of your projects.

To start genuinely from scratch, uninstall the app and then delete the `.openestimate` folder in your home directory yourself. That removes your projects, your users and every file you ever uploaded, with no undo, so copy it somewhere safe first unless you are certain. The next launch then behaves exactly like a first launch, database setup and demo account included.

## Need help

If something does not work or you have a question, email us at info@datadrivenconstruction.io, or open an issue on the project's GitHub issues page. We are happy to help.
