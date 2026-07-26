; Inno Setup Script for PCLink
; This script is a template and will be populated by the build process.

[Setup]
AppName=PCLink
AppVersion=__APP_VERSION__
AppPublisher=__COMPANY_NAME__
VersionInfoVersion=__FILE_VERSION__
VersionInfoProductVersion=__PRODUCT_VERSION__
AppCopyright=__COPYRIGHT__
AppPublisherURL=https://github.com/BYTEDz/PCLink
AppSupportURL=https://github.com/BYTEDz/PCLink/issues
DefaultDirName={autopf}\PCLink
DefaultGroupName=PCLink
DisableProgramGroupPage=yes
LicenseFile=__LICENSE_FILE__
OutputBaseFilename=__OUTPUT_BASE_FILENAME__
SetupIconFile=__SETUP_ICON_FILE__
OutputDir=__OUTPUT_DIR__
Compression=lzma2/ultra
SolidCompression=yes

WizardStyle=modern dynamic

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add PCLink executable directory to system PATH"; GroupDescription: "Environment Settings:"; Flags: checkedonce

[Files]
; This will grab the entire contents of the one-dir build output.
Source: "__SOURCE_DIR__\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PCLink"; Filename: "{app}\__EXECUTABLE_NAME__"
Name: "{group}\{cm:UninstallProgram,PCLink}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PCLink"; Filename: "{app}\__EXECUTABLE_NAME__"; Tasks: desktopicon

[Run]
Filename: "{app}\__EXECUTABLE_NAME__"; Description: "{cm:LaunchProgram,PCLink}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';

procedure AddToPath();
var
  OldPath, NewPath: string;
begin
  if RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OldPath) then
  begin
    if Pos(';' + ExpandConstant('{app}') + ';', ';' + OldPath + ';') = 0 then
    begin
      NewPath := OldPath + ';' + ExpandConstant('{app}');
      RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', NewPath);
    end;
  end;
end;

procedure RemoveFromPath();
var
  OldPath, NewPath: string;
  AppDir: string;
  P: Integer;
begin
  AppDir := ExpandConstant('{app}');
  if RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OldPath) then
  begin
    P := Pos(';' + AppDir, OldPath);
    if P > 0 then
    begin
      Delete(OldPath, P, Length(';' + AppDir));
      RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OldPath);
    end
    else
    begin
      P := Pos(AppDir + ';', OldPath);
      if P > 0 then
      begin
        Delete(OldPath, P, Length(AppDir + ';'));
        RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OldPath);
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
  begin
    AddToPath();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveFromPath();
  end;
end;
