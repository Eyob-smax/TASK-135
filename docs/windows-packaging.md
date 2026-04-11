# Windows Packaging Guide — District Console MSI Build

> **DELIVERY OVERRIDE (2026-04-11):** Dockerized deployment is the active delivery and acceptance
> path for this project. The MSI packaging guide below is **reference documentation only** and
> does not constitute a delivery requirement. All acceptance criteria are verified via the
> `docker-compose.yml` workflow. MSI guidance is retained for future Windows-native distribution.

> **Status:** Implemented. The WiX installer template (`installer/district-console.wxs`) and
> application icon (`backend/src/district_console/ui/resources/icon.ico`) are both present in the
> repository. The official acceptance and verification path is Docker-based (see
> `repo/docker-compose.yml`); the MSI build is the Windows-native distribution path.

---

## Overview

District Console targets Windows 11 for native deployment. The distribution artifact is a signed `.msi` installer built from the Python application using:
- **PyInstaller** — freezes the Python application and all dependencies into a self-contained directory
- **WiX Toolset** — compiles the frozen directory into an `.msi` Windows Installer package
- **signtool.exe** — signs the `.msi` with an organization-provided code-signing certificate

---

## Prerequisites

Before executing these steps, the following must be available on the build machine:

| Requirement | Notes |
|---|---|
| Python 3.10.x | Must match the runtime version used in development |
| PyInstaller 6.x | `pip install pyinstaller>=6.0` |
| WiX Toolset 4.x | Download from [wixtoolset.org](https://wixtoolset.org); add `wix` to PATH |
| Windows SDK (signtool.exe) | Included in Visual Studio Build Tools or Windows SDK installer |
| Organization code-signing certificate | Provided by the organization's release process. May be OV (Organization Validation) or EV (Extended Validation) depending on distribution requirements. Certificate file and private key must not be committed to this repository. |

> **Certificate note:** The signing workflow depends on your organization's release process. OV certificates are sufficient for internal distribution and reduce SmartScreen warnings. EV certificates eliminate SmartScreen warnings on first run and are required for kernel-mode driver signing, but are not mandatory for desktop application installers. Consult your organization's IT/security team for the applicable certificate tier and storage mechanism (PFX file, HSM, or Azure Key Vault).

---

## Step 1: Prepare the Build Environment

```bat
REM Create and activate a clean virtual environment
python -m venv build_env
build_env\Scripts\activate

REM Install the application and runtime dependencies
pip install -r repo\backend\requirements.txt
pip install pyinstaller>=6.0
```

---

## Step 2: Freeze with PyInstaller

```bat
cd repo\backend

pyinstaller ^
    --name district-console ^
    --onedir ^
    --windowed ^
    --icon src\district_console\ui\resources\icon.ico ^
    --add-data "src\district_console\ui\resources;district_console\ui\resources" ^
    --hidden-import district_console.bootstrap ^
    --hidden-import district_console.api ^
    src\district_console\bootstrap\__main__.py
```

Output: `dist\district-console\` — a self-contained directory with the executable and all dependencies.

> **Note:** PyQt6 requires additional WinDeploy steps or explicit DLL collection. If Qt plugins are missing at runtime, add `--collect-all PyQt6` to the PyInstaller command.

---

## Step 3: Create the WiX Source File

WiX reads a `.wxs` XML source file that describes the installer structure. Generate a component fragment from the frozen directory:

```bat
wix extension add WixToolset.UI.wixext
wix extension add WixToolset.Util.wixext
```

Create `installer\district-console.wxs` describing:
- Product metadata (name, version, manufacturer, upgrade code)
- Directory structure mirroring `dist\district-console\`
- Start Menu shortcut
- Desktop shortcut (optional)
- `INSTALLFOLDER` defaulting to `%ProgramFiles%\District Console`

Reference `installer\district-console.wxs` in the repository for the full template.

---

## Step 4: Build the MSI

```bat
wix build installer\district-console.wxs ^
    -ext WixToolset.UI.wixext ^
    -out dist\district-console-0.1.0.msi
```

Verify the `.msi` was created: `dir dist\district-console-0.1.0.msi`

---

## Step 5: Sign the MSI

Using an organization-provided certificate stored as a PFX file:

```bat
signtool sign ^
    /fd SHA256 ^
    /td SHA256 ^
    /tr http://timestamp.digicert.com ^
    /f path\to\org-cert.pfx ^
    /p <certificate_password> ^
    dist\district-console-0.1.0.msi
```

If using a Hardware Security Module (HSM) or Azure Key Vault, replace `/f` and `/p` with the appropriate provider flags per your HSM vendor's signtool integration guide.

> **Security note:** Never commit certificate files, passwords, or private keys to this repository. Use environment variables or a secrets manager to pass certificate credentials to the build pipeline.

---

## Step 6: Verify the Signature

```bat
signtool verify /pa /v dist\district-console-0.1.0.msi
```

Expected output: `Successfully verified: dist\district-console-0.1.0.msi`

Alternatively, use `sigcheck` from Sysinternals:
```bat
sigcheck -a dist\district-console-0.1.0.msi
```

---

## Silent Installation

The generated `.msi` supports silent installation for managed deployment:

```bat
msiexec /i district-console-0.1.0.msi /qn /l*v install.log
```

Custom install directory:
```bat
msiexec /i district-console-0.1.0.msi /qn INSTALLFOLDER="D:\Apps\DistrictConsole"
```

---

## Upgrade and Rollback

- Each release must increment the `Version` attribute in `.wxs` and use a **new unique GUID** for `UpgradeCode` if the product family changes, or keep the same `UpgradeCode` for in-place upgrades.
- WiX `MajorUpgrade` element handles automatic removal of the prior version before installation.
- The application's own offline update mechanism (`/api/v1/updates/import`) provides update and rollback without requiring MSI re-execution for patch releases.

---

## Known Limitations at Current Stage

- The `installer\district-console.wxs` template uses a single `ApplicationFiles` component group
  that references the main executable. For production builds, replace with `wix harvest` (WiX v4)
  output to capture all PyInstaller-generated `.dll` and data files automatically.
- The application icon at `src\district_console\ui\resources\icon.ico` is a minimal 16×16
  placeholder. Replace with a full multi-resolution ICO (16/32/48/256 px) before shipping.
- MSI post-build signing (`signtool.exe`) must be executed in a CI environment with access to
  the organization's code-signing certificate; no certificate is committed to this repository.
