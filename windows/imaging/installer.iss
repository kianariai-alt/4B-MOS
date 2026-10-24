; Per-user installer: the complete frozen application remains a replaceable
; directory of shared libraries. Setup itself is a single self-contained file.
#ifndef PayloadDir
  #error PayloadDir must point to the verified PyInstaller onedir output.
#endif
#ifndef SetupOutputDir
  #error SetupOutputDir must be supplied by build-installer.ps1.
#endif

[Setup]
AppId={{A77CBACD-739F-4BD9-9399-A17719B3B061}
AppName=4B Imaging
AppVersion=0.1.1
AppPublisher=4B-MOS
DefaultDirName={localappdata}\Programs\4B Imaging
DefaultGroupName=4B Imaging
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\4B-Imaging.exe
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes
OutputDir={#SetupOutputDir}
OutputBaseFilename=4B-Imaging-Setup-x64
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\4B Imaging"; Filename: "{app}\4B-Imaging.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\4B Imaging"; Filename: "{app}\4B-Imaging.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\4B-Imaging.exe"; Description: "Launch 4B Imaging"; Flags: nowait postinstall skipifsilent
