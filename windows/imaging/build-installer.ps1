param([string]$IsccPath)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Payload = Join-Path $Repo 'dist/4B-Imaging'
$Output = Join-Path $Repo 'dist/imaging-setup'
if (-not (Test-Path (Join-Path $Payload '4B-Imaging.exe')) -or
    -not (Test-Path (Join-Path $Payload '_internal/python312.dll'))) {
    throw 'Build the complete desktop payload with build.ps1 first.'
}
if (-not $IsccPath) {
    $IsccPath = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
}
if (-not (Test-Path $IsccPath)) {
    throw 'Inno Setup 6.3 or newer is required. Use its official installer from jrsoftware.org.'
}
New-Item -ItemType Directory -Path $Output -Force | Out-Null
& $IsccPath '/Qp' "/DPayloadDir=$Payload" "/DSetupOutputDir=$Output" (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Windows installer compilation failed.' }
Write-Output "Ready: $Output/4B-Imaging-Setup-x64.exe"
