# Windows installer build

The Windows installer is built on a Windows GitHub Actions runner. It bundles
Python, PySide6/Qt, python-can, serial support, ISO-TP/UDS helpers, optional DBC
support, and the FreeRov3r application into an installable Windows x64 package.

## Build automatically

- Every push to `main` runs the Windows installer workflow.
- Open **Actions → Windows installer → Run workflow** to build on demand.
- Download the `FreeRov3r-Windows-Installer` artifact from the completed run.
- Pushing a version tag such as `v0.1.0` also attaches the installer to a GitHub
  release.

The installer creates Start Menu shortcuts and offers an optional desktop
shortcut. Application settings, vehicle profiles, and capture data remain in
`%USERPROFILE%\.freerov3r` and are not removed by uninstalling the application.

The package is currently unsigned. Windows SmartScreen may display an unknown
publisher warning until the executable is signed with a trusted code-signing
certificate. The installer is x64 and targets Windows 10/11.

## Local build

From the repository root in PowerShell:

```powershell
python -m pip install -e ".[protocols,dev]" pyinstaller
python -m pytest -q
pyinstaller --noconfirm --clean --windowed --onedir --name FreeRov3r --paths src --collect-all PySide6 --collect-all can --collect-all serial --collect-all isotp --collect-all udsoncan --collect-all cantools --add-data "src/freerov3r/assets;freerov3r/assets" packaging/launcher.py
choco install innosetup --yes
iscc packaging/FreeRov3r.iss
```

Installer output: `dist-installer/FreeRov3r-Setup-0.1.0-x64.exe`.
