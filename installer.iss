; Inno Setup script for BHTOM Uploader
; Build: 1) PyInstaller build into dist\BHTOM Uploader (see README)
;        2) ISCC.exe installer.iss  ->  dist\BHTOM-Uploader-Setup-<version>.exe
; Per-user install (no admin rights needed), desktop icon optional, clean uninstall.

#define MyAppName "BHTOM Uploader"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Ihorrrzzz"
#define MyAppURL "https://github.com/Ihorrrzzz/bh-tom-uploader"
#define MyAppExeName "BHTOM Uploader.exe"

[Setup]
AppId={{A7C41B0E-4D33-4B7A-9C55-1BB0F2E6D410}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={userpf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=BHTOM-Uploader-Setup-{#MyAppVersion}
SetupIconFile=bhtom_uploader\resources\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\BHTOM Uploader\*"; DestDir: "{app}"; Excludes: "smoke_result.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: contains only the application bundle + config.ini (service URLs).
; No user credentials are ever inside: those live in Windows Credential Manager.

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
