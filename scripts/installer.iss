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
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; This will grab the entire contents of the one-dir build output.
Source: "__SOURCE_DIR__\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PCLink"; Filename: "{app}\__EXECUTABLE_NAME__"
Name: "{group}\{cm:UninstallProgram,PCLink}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PCLink"; Filename: "{app}\__EXECUTABLE_NAME__"; Tasks: desktopicon

[Run]
Filename: "{app}\__EXECUTABLE_NAME__"; Description: "{cm:LaunchProgram,PCLink}"; Flags: nowait postinstall skipifsilent