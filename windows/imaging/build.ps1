param([switch]$UseCurrentPython)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$TemplateRoot = Join-Path $Repo 'backend/tools/knee_templates'
Set-Location $Repo
if ($UseCurrentPython) {
    $Python = (Get-Command python).Source
} else {
    py -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
    $Python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
}
& $Python -m pip install -r backend/requirements-imaging-desktop.txt 'pyinstaller==6.16.0'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name 4B-Imaging `
    --paths $Repo --specpath build/imaging-desktop `
    --add-data "$TemplateRoot;backend/tools/knee_templates" `
    --copy-metadata pydicom `
    --collect-submodules pydicom.pixels.decoders `
    --hidden-import vtkmodules.vtkRenderingOpenGL2 `
    --hidden-import vtkmodules.vtkRenderingVolumeOpenGL2 `
    --hidden-import vtkmodules.vtkInteractionStyle `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 `
    windows/imaging/entry.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed.' }
Copy-Item windows/imaging/README-FA.txt dist/4B-Imaging/README-FA.txt
Copy-Item backend/tools/knee_templates/ATTRIBUTION.md dist/4B-Imaging/ANATOMY_ATTRIBUTION.md
& $Python windows/imaging/collect_licenses.py dist/4B-Imaging/licenses
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
Write-Output 'Ready: dist/4B-Imaging/4B-Imaging.exe'
