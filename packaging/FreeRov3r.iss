#define AppName "FreeRov3r"
#define AppVersion "0.1.0"
#define AppPublisher "FreeRov3r Project"
#define AppExeName "FreeRov3r.exe"

[Setup]
AppId={{9C7A8D52-68B9-4B31-A87D-2D54B80C3F20}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\FreeRov3r
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist-installer
OutputBaseFilename=FreeRov3r-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\FreeRov3r\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FreeRov3r"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\FreeRov3r"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch FreeRov3r"; Flags: postinstall nowait skipifsilent
