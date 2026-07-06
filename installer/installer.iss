#ifndef AppName
  #define AppName "KaraokeMachine"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.1"
#endif
#ifndef AppPublisher
  #define AppPublisher "forbenaj"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "KaraokeMachineSetup"
#endif

[Setup]
AppId={{9B76CE9F-75B3-4F13-94A6-611E423605E0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\KaraokeMachine
DefaultGroupName=KaraokeMachine
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\icons\icon128.png
UninstallDisplayName=KaraokeMachine

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.gitignore,.pytest_cache\*,.venv-*\*,.stem-models\*,node_modules\*,downloads\*,cache\*,separated\*,tests\*,demo\*,installer\*,AGENTS.md,host\dkaraoke_host.cmd,host\com.dkaraoke.downloader.json,*.pyc,__pycache__\*"

[Icons]
Name: "{autoprograms}\KaraokeMachine\KaraokeMachine Extension Folder"; Filename: "{app}"
Name: "{autoprograms}\KaraokeMachine\KaraokeMachine Setup Log"; Filename: "notepad.exe"; Parameters: """{localappdata}\DKaraoKe\setup.log"""
Name: "{autoprograms}\KaraokeMachine\Uninstall KaraokeMachine"; Filename: "{uninstallexe}"

[Run]
Filename: "{code:GetChromePath}"; Parameters: "chrome://extensions"; Description: "Open Chrome extensions page"; Flags: postinstall nowait skipifsilent unchecked; Check: HasChrome

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"""; Flags: waituntilterminated runhidden; RunOnceId: "KaraokeMachineNativeHost"

[UninstallDelete]
Type: files; Name: "{app}\host\dkaraoke_host.cmd"
Type: files; Name: "{app}\host\com.dkaraoke.downloader.json"
Type: filesandordirs; Name: "{app}\.venv-tools"
Type: filesandordirs; Name: "{app}\.venv-roformer"
Type: filesandordirs; Name: "{app}\.stem-models"
Type: dirifempty; Name: "{app}"

[Code]
var
  DownloadsPage: TInputDirWizardPage;
  OptionsPage: TWizardPage;
  TorchCombo: TNewComboBox;
  InstallRoFormerCheck: TNewCheckBox;
  SkipFfmpegCheck: TNewCheckBox;
  ExtensionFolderLabel: TNewStaticText;
  ExtensionFolderEdit: TNewEdit;

procedure InitializeWizard;
var
  TorchLabel: TNewStaticText;
  HintLabel: TNewStaticText;
begin
  DownloadsPage := CreateInputDirPage(
    wpSelectDir,
    'Choose stems folder',
    'Where should KaraokeMachine save separated audio and lyrics?',
    'KaraokeMachine keeps prepared songs here so it can reuse them later. You can keep the default folder or choose a larger drive.',
    False,
    ''
  );
  DownloadsPage.Add('Stems and downloads folder:');
  DownloadsPage.Values[0] := ExpandConstant('{localappdata}\KaraokeMachine\downloads');

  OptionsPage := CreateCustomPage(
    DownloadsPage.ID,
    'Choose setup options',
    'Pick the audio separation runtime for this computer.'
  );

  TorchLabel := TNewStaticText.Create(OptionsPage);
  TorchLabel.Parent := OptionsPage.Surface;
  TorchLabel.Left := 0;
  TorchLabel.Top := 0;
  TorchLabel.Width := OptionsPage.SurfaceWidth;
  TorchLabel.Caption := 'Torch build for RoFormer:';

  TorchCombo := TNewComboBox.Create(OptionsPage);
  TorchCombo.Parent := OptionsPage.Surface;
  TorchCombo.Left := 0;
  TorchCombo.Top := TorchLabel.Top + TorchLabel.Height + 8;
  TorchCombo.Width := 220;
  TorchCombo.Style := csDropDownList;
  TorchCombo.Items.Add('CPU');
  TorchCombo.Items.Add('CUDA 12.1');
  TorchCombo.Items.Add('CUDA 12.4');
  TorchCombo.ItemIndex := 0;

  HintLabel := TNewStaticText.Create(OptionsPage);
  HintLabel.Parent := OptionsPage.Surface;
  HintLabel.Left := 0;
  HintLabel.Top := TorchCombo.Top + TorchCombo.Height + 8;
  HintLabel.Width := OptionsPage.SurfaceWidth;
  HintLabel.Height := 58;
  HintLabel.WordWrap := True;
  HintLabel.Caption := 'CPU is safest for setup. CUDA builds are faster later, but need a compatible NVIDIA driver. Setup installs Python 3.12 with winget if needed.';

  InstallRoFormerCheck := TNewCheckBox.Create(OptionsPage);
  InstallRoFormerCheck.Parent := OptionsPage.Surface;
  InstallRoFormerCheck.Left := 0;
  InstallRoFormerCheck.Top := HintLabel.Top + HintLabel.Height + 10;
  InstallRoFormerCheck.Width := OptionsPage.SurfaceWidth;
  InstallRoFormerCheck.Caption := 'Install RoFormer now (recommended)';
  InstallRoFormerCheck.Checked := True;

  SkipFfmpegCheck := TNewCheckBox.Create(OptionsPage);
  SkipFfmpegCheck.Parent := OptionsPage.Surface;
  SkipFfmpegCheck.Left := 0;
  SkipFfmpegCheck.Top := InstallRoFormerCheck.Top + InstallRoFormerCheck.Height + 8;
  SkipFfmpegCheck.Width := OptionsPage.SurfaceWidth;
  SkipFfmpegCheck.Caption := 'Skip FFmpeg install if ffmpeg and ffprobe are already on PATH';
  SkipFfmpegCheck.Checked := False;

  ExtensionFolderLabel := TNewStaticText.Create(WizardForm);
  ExtensionFolderLabel.Parent := WizardForm.FinishedPage;
  ExtensionFolderLabel.Left := WizardForm.FinishedLabel.Left;
  ExtensionFolderLabel.Top := WizardForm.FinishedLabel.Top + ScaleY(152);
  ExtensionFolderLabel.Width := WizardForm.FinishedLabel.Width;
  ExtensionFolderLabel.Caption := 'Extension folder to load in Chrome:';

  ExtensionFolderEdit := TNewEdit.Create(WizardForm);
  ExtensionFolderEdit.Parent := WizardForm.FinishedPage;
  ExtensionFolderEdit.Left := WizardForm.FinishedLabel.Left;
  ExtensionFolderEdit.Top := ExtensionFolderLabel.Top + ExtensionFolderLabel.Height + ScaleY(6);
  ExtensionFolderEdit.Width := WizardForm.FinishedLabel.Width;
  ExtensionFolderEdit.ReadOnly := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DownloadsPage.ID then begin
    if Trim(DownloadsPage.Values[0]) = '' then begin
      MsgBox('Choose a folder where Karaoke Machine! can save stems and downloads.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function GetDownloadsDir(Param: String): String;
begin
  Result := DownloadsPage.Values[0];
end;

function GetTorchBuild(Param: String): String;
begin
  case TorchCombo.ItemIndex of
    1: Result := 'cu121';
    2: Result := 'cu124';
  else
    Result := 'cpu';
  end;
end;

function GetSkipRoFormerArg(Param: String): String;
begin
  if InstallRoFormerCheck.Checked then
    Result := ''
  else
    Result := '-SkipRoFormerSetup';
end;

function GetSkipFfmpegArg(Param: String): String;
begin
  if SkipFfmpegCheck.Checked then
    Result := '-SkipFfmpegInstall'
  else
    Result := '';
end;

function QuoteParam(Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function GetChromePath(Param: String): String;
var
  Path: String;
begin
  Path := ExpandConstant('{autopf}\Google\Chrome\Application\chrome.exe');
  if FileExists(Path) then begin
    Result := Path;
    exit;
  end;

  Path := ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe');
  if FileExists(Path) then begin
    Result := Path;
    exit;
  end;

  Result := '';
end;

function HasChrome: Boolean;
begin
  Result := GetChromePath('') <> '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Parameters: String;
  PowerShell: String;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Setting up KaraokeMachine... This can take a while when RoFormer is installed.';
    PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Parameters :=
      '-NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteParam(ExpandConstant('{app}\scripts\setup-wizard.ps1')) +
      ' -InstallDir ' + QuoteParam(ExpandConstant('{app}')) +
      ' -DownloadsDir ' + QuoteParam(GetDownloadsDir('')) +
      ' -TorchBuild ' + GetTorchBuild('') +
      ' ' + GetSkipRoFormerArg('') +
      ' ' + GetSkipFfmpegArg('');

    if not Exec(PowerShell, Parameters, ExpandConstant('{app}'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then begin
      RaiseException('Could not start KaraokeMachine setup. See %LOCALAPPDATA%\DKaraoKe\setup.log if it was created.');
    end;
    if ResultCode <> 0 then begin
      RaiseException('KaraokeMachine setup failed. See %LOCALAPPDATA%\DKaraoKe\setup.log for details.');
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    ExtensionFolderEdit.Text := ExpandConstant('{app}');
    WizardForm.FinishedLabel.Caption :=
      'KaraokeMachine is installed. Chrome still needs the extension loaded manually:' + #13#10 + #13#10 +
      '1. Open chrome://extensions' + #13#10 +
      '2. Enable Developer mode' + #13#10 +
      '3. Click Load unpacked' + #13#10 +
      '4. Select the extension folder below' + #13#10 +
      '5. Restart Chrome if it was open during setup';
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then begin
    MsgBox(
      'KaraokeMachine has been uninstalled. Cached stems and lyrics remain in the configured downloads folder unless you remove them manually.',
      mbInformation,
      MB_OK
    );
  end;
end;
