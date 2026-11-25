; Instalador da Central WB (central do fornecedor) para Windows. Montado no GitHub:
;   iscc /DVersao=1.0.0 /DOrigem=<pasta do build> /DSaida=<pasta> apps\windows-central\central.iss
; Instala só para o usuário (sem pedir administrador), com atalho na área de trabalho e no menu Iniciar.
#ifndef Versao
  #define Versao "1.0.0"
#endif
#ifndef Origem
  #define Origem "bin\Release\net48"
#endif
#ifndef Saida
  #define Saida "dist"
#endif

[Setup]
AppId={{6B0E2F3C-5C7A-4E55-9D7B-8C1F0A2E4B11}
AppName=Central WB
AppVersion={#Versao}
AppPublisher=WB Sistemas
AppPublisherURL=https://willpdv.com.br
DefaultDirName={localappdata}\Programs\Central WB
DefaultGroupName=Central WB
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Saida}
OutputBaseFilename=CentralWB-Setup-{#Versao}
SetupIconFile=CentralWB.ico
UninstallDisplayIcon={app}\CentralWB.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs; Excludes: "*.pdb,*.xml"

[Icons]
Name: "{group}\Central WB"; Filename: "{app}\CentralWB.exe"
Name: "{userdesktop}\Central WB"; Filename: "{app}\CentralWB.exe"; Tasks: atalho

[Run]
Filename: "{app}\CentralWB.exe"; Description: "Abrir a Central WB agora"; Flags: nowait postinstall skipifsilent
