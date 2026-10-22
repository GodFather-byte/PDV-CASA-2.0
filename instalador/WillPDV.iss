; Instalador do WillPDV (Inno Setup 6.3 ou mais novo).
;
; Antes, gere o executável:  python build_pdv.py --sem-instalador   (cria dist\WillPDV\)
; Depois abra este arquivo no Inno Setup e clique em Build > Compile, ou rode só  python build_pdv.py,  que faz os dois.
; O instalador sai em instalador\saida\WillPDV-Setup-<versão>.exe
;
; Os dados do caixa (banco, backups, licença, logs) NÃO ficam na pasta do programa: ficam em %LOCALAPPDATA%\WILL-PDV
; do usuário do Windows. Por isso atualizar ou desinstalar o programa não apaga as vendas.

#ifndef Versao
  #define Versao "1.8.0"          ; o build_pdv.py passa a versão de src\versao.py (/DVersao=...)
#endif
#define Nome "WillPDV"
#define Exe "WillPDV.exe"

; Sem o executável o Inno só diria "No files found": explica o que fazer antes.
#if !FileExists(SourcePath + "..\dist\WillPDV\" + Exe)
  #error Falta gerar o programa: abra o Prompt de Comando na pasta do projeto e rode  python build_pdv.py --sem-instalador  (cria a pasta dist\WillPDV). Depois compile este arquivo de novo.
#endif

[Setup]
; O AppId identifica o programa no Windows: NUNCA troque, senão a atualização vira uma segunda instalação.
AppId={{D44B21FE-DB95-446D-956E-5EAAD7642753}
AppName={#Nome}
AppVersion={#Versao}
AppVerName={#Nome} {#Versao}
AppPublisher=WillyanPHP
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#Exe}
OutputDir=saida
OutputBaseFilename=WillPDV-Setup-{#Versao}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; O executável gerado por um Python 64 bits só roda em Windows 64 bits.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Atualização com o caixa aberto: o instalador pede para fechar o WillPDV antes de copiar os arquivos.
CloseApplications=yes
RestartApplications=no
#ifdef Icone
SetupIconFile={#Icone}
#endif
; Logotipo no assistente (painel da esquerda 164x314 e imagem pequena 55x55). Para usar a sua marca, troque esses .bmp pelos seus.
#if FileExists(SourcePath + "willpdv-assistente.bmp")
WizardImageFile=willpdv-assistente.bmp
WizardSmallImageFile=willpdv-assistente-pequena.bmp
#endif

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"
Name: "iniciarcomwindows"; Description: "Abrir o caixa automaticamente ao ligar o computador"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "nuvem"; Description: "Verificar licença e atualizações na nuvem em segundo plano (ao ligar o computador)"; GroupDescription: "Nuvem:"; Flags: unchecked

[Files]
; Toda a pasta gerada pelo PyInstaller (o .exe e as bibliotecas ao lado dele).
Source: "..\dist\WillPDV\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{autoprograms}\{#Nome} Qt (prévia)"; Filename: "{app}\{#Exe}"; Parameters: "--qt"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Exe}"; Tasks: desktopicon
Name: "{autostartup}\{#Nome}"; Filename: "{app}\{#Exe}"; Tasks: iniciarcomwindows
Name: "{autostartup}\{#Nome} - envio para a nuvem"; Filename: "{app}\{#Exe}"; Parameters: "--sync"; Tasks: nuvem

[Run]
; Abre como o usuário que instalou (não como administrador): os dados ficam no %LOCALAPPDATA% dele.
Filename: "{app}\{#Exe}"; Description: "Abrir o {#Nome} agora"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
// WillPDV.exe esquecido rodando (a tela de entrada aberta atrás de outras janelas, ou o processo de segundo plano --sync, que nem
// janela tem) trava a instalação em "os aplicativos a seguir estão usando arquivos que precisam ser atualizados": o Restart Manager
// só consegue fechar quem tem janela. Por isso, antes de copiar os arquivos, o instalador avisa e encerra o que sobrou.
// Os dados não correm risco: o banco grava cada venda na hora (SQLite), e ele fica fora da pasta do programa.
function WillPDVRodando(): Boolean;
var
  Codigo: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'),
    '/C tasklist /NH /FI "IMAGENAME eq {#Exe}" | find /I "{#Exe}" >nul', '', SW_HIDE, ewWaitUntilTerminated, Codigo)
    and (Codigo = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Result := '';
  if not WillPDVRodando() then
    Exit;
  if not WizardSilent then
    if MsgBox('O WillPDV está aberto neste computador (talvez escondido, sem janela).' + #13#10 + #13#10 +
              'Para instalar, o instalador precisa fechá-lo agora. As vendas já gravadas ficam salvas.' + #13#10 + #13#10 +
              'Fechar o WillPDV e continuar?', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := 'Feche o WillPDV (ou finalize o WillPDV.exe no Gerenciador de Tarefas) e rode o instalador de novo.';
      Exit;
    end;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#Exe}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Sleep(1500);
end;
