# Test the delivered files, including the Explorer ZIP execution failure mode.
# Only generated DICOM is used; no network, patient file or production service.
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Payload = Join-Path $Repo 'dist/4B-Imaging'
$Setup = Join-Path $Repo 'dist/imaging-setup/4B-Imaging-Setup-x64.exe'
$VerificationRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('4b-imaging-package-' + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $VerificationRoot | Out-Null

function Invoke-CheckedProcess([string]$Executable, [string]$Arguments, [int]$Timeout = 120000) {
    $Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    if (-not $Process.WaitForExit($Timeout)) {
        $Process.Kill()
        throw 'Package verification process exceeded its time limit.'
    }
    if ($Process.ExitCode -ne 0) { throw "Package verification process exited with code $($Process.ExitCode)." }
}

function Assert-CompleteBundle([string]$Directory) {
    foreach ($Name in @('4B-Imaging.exe', '_internal/python312.dll', 'README-FA.txt', 'ANATOMY_ATTRIBUTION.md')) {
        if (-not (Test-Path (Join-Path $Directory $Name) -PathType Leaf)) {
            throw "Incomplete desktop bundle: $Name"
        }
    }
    foreach ($Name in @('QtWebEngineProcess.exe', 'icudtl.dat')) {
        if (-not (Get-ChildItem $Directory -Filter $Name -Recurse -File)) {
            throw "Missing embedded browser component: $Name"
        }
    }
}

function Assert-CoreWorks([string]$Directory, [string]$Report) {
    Assert-CompleteBundle $Directory
    try {
        Invoke-CheckedProcess (Join-Path $Directory '4B-Imaging.exe') "--self-test-core `"$Report`""
    } catch {
        # The CLI report contains generated test data only, never a patient input.
        if (Test-Path $Report) { Get-Content $Report -Raw | Write-Output }
        throw
    }
    $Result = Get-Content $Report -Raw | ConvertFrom-Json
    if ($Result.core_self_test -ne 'passed' -or $Result.synthetic_only -ne $true) {
        throw 'The delivered application did not pass its generated-DICOM self-test.'
    }
}

try {
    Assert-CompleteBundle $Payload
    $Zip = Join-Path $VerificationRoot 'portable.zip'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Payload, $Zip)
    $Extracted = Join-Path $VerificationRoot 'Extracted portable package'
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Extracted)
    Assert-CoreWorks $Extracted (Join-Path $VerificationRoot 'extracted core report.json')

    # Windows Explorer may copy just the clicked EXE out of a ZIP. Copy ONLY
    # Setup.exe to an isolated directory to prove it needs no adjacent payload.
    $SetupOnly = Join-Path $VerificationRoot 'Only the setup file'
    New-Item -ItemType Directory -Path $SetupOnly | Out-Null
    $IsolatedSetup = Join-Path $SetupOnly '4B-Imaging-Setup-x64.exe'
    Copy-Item $Setup $IsolatedSetup
    $Installed = Join-Path $VerificationRoot 'Installed Imaging'
    Invoke-CheckedProcess $IsolatedSetup "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=`"$Installed`""
    Assert-CoreWorks $Installed (Join-Path $VerificationRoot 'installed core report.json')

    $Uninstaller = Join-Path $Installed 'unins000.exe'
    if (-not (Test-Path $Uninstaller)) { throw 'The installed application has no uninstaller.' }
    Invoke-CheckedProcess $Uninstaller '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
    if (Test-Path (Join-Path $Installed '4B-Imaging.exe')) {
        throw 'The application executable remained after uninstall.'
    }

    $Summary = [ordered]@{
        synthetic_only = $true
        extracted_zip_core_test = 'passed'
        self_contained_setup_test = 'passed'
        installed_core_test = 'passed'
        uninstall_test = 'passed'
        paths_with_spaces_test = 'passed'
        installer_sha256 = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLowerInvariant()
        installer_bytes = (Get-Item $Setup).Length
    }
    $Summary | ConvertTo-Json | Set-Content (Join-Path $Repo 'dist/imaging-setup/setup-verification.json') -Encoding utf8
    $Summary | ConvertTo-Json | Write-Output
} finally {
    # Inno's delayed self-deletion may remove a child while cleanup enumerates
    # this generated-data-only directory. Never replace the verification result
    # with that disposable-runner cleanup race.
    for ($Attempt = 0; $Attempt -lt 3 -and (Test-Path $VerificationRoot); $Attempt++) {
        try {
            [System.IO.Directory]::Delete($VerificationRoot, $true)
        } catch {
            if ($Attempt -eq 2 -and (Test-Path $VerificationRoot)) {
                Write-Warning 'Temporary synthetic package cleanup was deferred to runner disposal.'
            } else {
                Start-Sleep -Milliseconds 300
            }
        }
    }
}
