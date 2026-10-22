; Instalador do WillPDV Licenças (Inno Setup 6.3 ou mais novo): o programa do FORNECEDOR que emite as licenças.
;
; Antes, gere o executável:  python build_licenciador.py --sem-instalador   (cria dist\WillLicencas\)
; Depois compile este arquivo, ou rode só  python build_licenciador.py,  que faz os dois.
; O instalador sai em instalador\saida\WillLicencas-Setup-<versão>.exe
;
; NÃO entregue este instalador a clientes: ele serve para quem vende o WillPDV. A chave privada fica em
; %USERPROFILE%\.pdv-casa\licenca_privada.key e o histórico em %LOCALAPPDATA%\WillPDV-Licencas; nenhum dos dois é apagado
; ao atualizar ou desinstalar o programa.

#ifndef Versao
  #define Versao "1.2.0"          ; o build_licenciador.py passa a versão de licenciador\nucleo.py (/DVersao=...)
#endif
#define Nome "WillPDV Licenças"
#define Exe "WillLicencas.exe"

#if !FileExists(SourcePath + "..\dist\WillLicencas\" + Exe)
  #error Falta gerar o programa: rode  python build_licenciador.py --sem-instalador  (cria a pasta dist\WillLicencas). Depois compile este arquivo de novo.
#endif

[Setup]
; O AppId identifica o programa no Windows: NUNCA troque, senão a atualização vira uma segunda instalação.
; É diferente do AppId do WillPDV: os dois instalam lado a lado.
AppId={{5A64092B-CF3A-41F7-82B8-CB80772F40C9}
AppName={#Nome}
AppVersion={#Versao}
AppVerName={#Nome} {#Versao}
AppPublisher=WillyanPHP
DefaultDirName={autopf}\WillLicencas
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#Exe}
OutputDir=saida
OutputBaseFilename=WillLicencas-Setup-{#Versao}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Ferramenta de uma pessoa só, sem serviço nem driver: instala para o usuário, sem pedir senha de administrador.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
#ifdef Icone
SetupIconFile={#Icone}
#endif
#if FileExists(SourcePath + "willlicencas-assistente.bmp")
WizardImageFile=willlicencas-assistente.bmp
WizardSmallImageFile=willlicencas-assistente-pequena.bmp
#endif

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\WillLicencas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Exe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Exe}"; Description: "Abrir o {#Nome} agora"; Flags: nowait postinstall skipifsilent

[Code]
// Programa esquecido rodando (sem janela visível) trava a atualização em "os aplicativos a seguir estão usando arquivos": o Restart
// Manager só fecha quem tem janela. Antes de copiar os arquivos o instalador avisa e encerra o que sobrou. O que importa (a chave e o
// histórico) fica fora da pasta do programa.
function ProgramaRodando(): Boolean;
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
  if not ProgramaRodando() then
    Exit;
  if not WizardSilent then
    if MsgBox('O {#Nome} está aberto neste computador (talvez escondido).' + #13#10 + #13#10 +
              'Para instalar, o instalador precisa fechá-lo agora. Sua chave e o histórico de licenças ficam guardados.' + #13#10 + #13#10 +
              'Fechar e continuar?', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := 'Feche o {#Nome} (ou finalize o {#Exe} no Gerenciador de Tarefas) e rode o instalador de novo.';
      Exit;
    end;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#Exe}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Sleep(1500);
end;
