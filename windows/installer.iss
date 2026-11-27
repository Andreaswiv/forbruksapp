; Installasjonsfil for Windows (Inno Setup 6). Bygges av .github/workflows/windows.yml.
; Installerer uten administrator-passord, lager ikon på skrivebordet og i Start-menyen,
; og åpner appen når installasjonen er ferdig.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Pengene mine"
#define Launch "{app}\python\pythonw.exe"
#define LaunchArgs """{app}\app\launcher.py"""

[Setup]
AppId={{8F3C2A51-6B7D-4E0A-9C1E-5A2D7B9F4E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
ShowLanguageDialog=no
OutputDir=..\build
OutputBaseFilename=PengeneMine-installer
SetupIconFile=ikon.ico
UninstallDisplayIcon={app}\app\windows\ikon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Languages]
Name: "norsk"; MessagesFile: "compiler:Languages\Norwegian.isl"

[InstallDelete]
; Ny versjon: fjern gammel programkode først (dataene ligger et annet sted og blir ikke rørt)
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "..\build\PengeneMine\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{#Launch}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\windows\ikon.ico"
Name: "{autoprograms}\{#AppName}"; Filename: "{#Launch}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\windows\ikon.ico"

[Run]
Filename: "{#Launch}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}\app"; Description: "Åpne {#AppName} nå"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
