; Inno Setup script for the installed app (Windows). After PyInstaller (dist\cad-viewer):
;   iscc /DAppVersion=0.6.0 packaging\windows\cad-viewer.iss
; Installs for the current user only (%LOCALAPPDATA%\Programs\cad-viewer): no
; administrator's rights, no UAC prompt. The user's data (%LOCALAPPDATA%\cad-viewer:
; the measurements and notes) stays when the app is uninstalled.
; This file has a UTF-8 BOM: without it, Inno Setup reads it in the system's code page.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=X.Y.Z
#endif

[Setup]
; the same id in every version: a new one installs over the old
AppId={{C1A60544-5FCB-4E92-A03C-833728D355F6}
AppName=cad-viewer
AppVersion={#AppVersion}
AppVerName=cad-viewer {#AppVersion}
AppPublisher=shostako
AppPublisherURL=https://github.com/shostako/cad-viewer
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\cad-viewer
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=cad-viewer-setup-{#AppVersion}
SetupIconFile=cad-viewer.ico
UninstallDisplayIcon={app}\cad-viewer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作る"; GroupDescription: "アイコン:"

[Files]
Source: "..\..\dist\cad-viewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; the previous version's bundle: a library dropped in this version must not stay behind
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\cad-viewer"; Filename: "{app}\cad-viewer.exe"
Name: "{autodesktop}\cad-viewer"; Filename: "{app}\cad-viewer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\cad-viewer.exe"; Description: "cad-viewer を起動する"; Flags: nowait postinstall skipifsilent

[Code]
// The app runs in the background (its icon in the notification area): stopped
// before its files are replaced or removed. It keeps nothing unsaved (each
// measurement and note is saved as it is made).
procedure StopRunningApp();
var
  rc: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM cad-viewer.exe', '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;
