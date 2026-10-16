# Mandible DEVELOPER build script (PyInstaller + Inno Setup 6).
#
# Release binaries are built ONLY by CI (.github/workflows/release.yml). Output of this
# script is for local testing and must never be uploaded as a release.
$ErrorActionPreference = "Stop"

$Version = (Select-String -Path "mandible\_version.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value

$PyInstaller = ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) { $PyInstaller = "pyinstaller" }

Write-Host "==> [1/2] Building dist\Mandible\Mandible.exe ($Version, dev build)..." -ForegroundColor Cyan
& $PyInstaller --noconfirm --clean Mandible.spec

$IsccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Iscc) {
    Write-Host "==> [2/2] Building dev installer..." -ForegroundColor Cyan
    & $Iscc "/DMyAppVersion=$Version-dev" installer.iss
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found. Dev build available at dist\Mandible\Mandible.exe"
}
