; Lumen 音乐 Inno Setup 安装包脚本（per-user 免 UAC，公司规范）
; AppVersion 必须与 core/version.py、官网 publish.json 三处一致
#define AppName "Lumen 音乐"
#define AppVersion "1.5"
#define AppPublisher "深圳市创炫互动网络科技有限公司"
#define AppURL "https://www.mrheedu.com"
#define AppExeName "Lumen音乐.exe"
#define SourceDir "dist\Lumen音乐"
#define AppId "{{C8F10216-EB5C-4092-BD07-0C1EE8155990}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=Lumen音乐-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 关闭 RedirectionGuard:本包 per-user 免提权,且部分用户把 %LOCALAPPDATA%
; 重定向到其他盘的 junction 会被 RedirectionGuard 拦截(error 448)
RedirectionGuard=no
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
; 关联有变化时通知资源管理器刷新图标与右键菜单
ChangesAssociations=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "assoc"; Description: "注册音频文件关联（右键文件 → 打开方式 可选 Lumen 音乐，可设为默认）"; GroupDescription: "附加任务:"

[Registry]
; per-user 文件关联：只写 HKCU\Software\Classes，不弹 UAC，卸载自动清理
Root: HKCU; Subkey: "Software\Classes\Lumen.Audio"; ValueType: string; ValueName: ""; ValueData: "Lumen 音乐音频"; Flags: uninsdeletekey; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\Lumen.Audio\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Flags: uninsdeletekey; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\Lumen.Audio\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.aac\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.oga\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.opus\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.wma\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected
Root: HKCU; Subkey: "Software\Classes\.ape\OpenWithProgids"; ValueType: string; ValueName: "Lumen.Audio"; ValueData: ""; Flags: uninsdeletevalue; Check: AssocSelected

[Code]
function AssocSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('assoc');
end;

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent
