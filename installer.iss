; Mandible Windows installer (Inno Setup 6). Built only by CI.
; CI passes the version from mandible/_version.py:  ISCC /DMyAppVersion=x.y.z installer.iss
#define MyAppName "Mandible"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Xen10 Industries"
#define MyAppExeName "Mandible.exe"
#define MyAppURL "https://github.com/Xen10-Industries/Mandible"

[Setup]
; New AppId for Mandible (pre-release VoiceFX builds were never distributed).
AppId={{BB947B75-D1CB-44B7-9826-409AEDC1A5DD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (c) {#MyAppPublisher}. GPL-3.0-or-later.
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=Mandible-{#MyAppVersion}-Setup
SetupIconFile=Mandible.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Launch {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "dist\Mandible\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Mandible\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; License texts must ship with every release artifact.
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Software\Classes\.mandible"; ValueType: string; ValueName: ""; ValueData: "Xen10.Mandible.Preset"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Xen10.Mandible.Preset"; ValueType: string; ValueName: ""; ValueData: "Mandible Preset"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Xen10.Mandible.Preset\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",0"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Mandible never bundles third-party audio drivers. Users without Focusrite Loopback install VB-Cable themselves.
Filename: "https://vb-audio.com/Cable/"; Description: "Open the VB-Audio Virtual Cable download page (not needed with Focusrite Loopback)"; Flags: shellexec postinstall skipifsilent unchecked nowait
