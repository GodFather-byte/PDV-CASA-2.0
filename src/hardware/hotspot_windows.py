"""Wi-Fi próprio dos caixas: o caixa principal liga o "Hotspot móvel" do Windows e os caixas adicionais se conectam
nele. Assim a ligação entre os caixas não passa pelo roteador da loja: se o Wi-Fi ou a internet da loja cair, os
caixas continuam se falando (a internet do adicional passa pelo principal e volta sozinha quando a loja voltar).

O Windows às vezes desliga o hotspot sozinho (sem aparelho conectado, ou depois de suspender). Por isso o serviço
vigia a cada minuto e liga de novo. Também tenta tirar o desligamento automático (precisa de administrador; sem
permissão, a tela de Caixas da loja mostra onde desmarcar).

Tudo pelo PowerShell com as APIs do Windows (NetworkOperatorTetheringManager). Fora do Windows não faz nada.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading

log = logging.getLogger("pdv.hotspot")

CHAVE_LIGADO = "hotspot_caixas"
CHAVE_ESTADO = "hotspot_estado"          # JSON com o último estado visto (para a tela)
INTERVALO_SEG = 60
TEMPO_POWERSHELL = 40

_PREPARO = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Esperar($op, $tipo) { $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$perfil = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $perfil) {
  $perfil = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles() |
    Where-Object { $_.IsWlanConnectionProfile -or $_.IsWwanConnectionProfile } | Select-Object -First 1
}
if (-not $perfil) { '{"suportado": true, "ligado": false, "erro": "Sem rede para compartilhar agora."}'; exit }
$gerente = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($perfil)
"""

_LER = _PREPARO + r"""
$cfg = $gerente.GetCurrentAccessPointConfiguration()
@{ suportado = $true; ligado = ($gerente.TetheringOperationalState -eq 1); ssid = $cfg.Ssid; senha = $cfg.Passphrase;
   conectados = $gerente.ClientCount } | ConvertTo-Json -Compress
"""

_LIGAR = _PREPARO + r"""
if ($gerente.TetheringOperationalState -ne 1) {
  $r = Esperar ($gerente.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
  if ($r.Status -ne 0) { @{ suportado = $true; ligado = $false; erro = "O Windows não ligou o hotspot (" + $r.Status + "): " + $r.AdditionalErrorMessage } | ConvertTo-Json -Compress; exit }
}
try {
  New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Force | Out-Null
  Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name 'PeerlessTimeoutEnabled' -Value 0 -Type DWord
  $semTempo = $true
} catch { $semTempo = $false }
$cfg = $gerente.GetCurrentAccessPointConfiguration()
@{ suportado = $true; ligado = ($gerente.TetheringOperationalState -eq 1); ssid = $cfg.Ssid; senha = $cfg.Passphrase;
   conectados = $gerente.ClientCount; sem_desligamento = $semTempo } | ConvertTo-Json -Compress
"""


def suportado() -> bool:
    return sys.platform == "win32"


def _powershell(script: str, executar=None) -> dict:
    if executar is None:
        if not suportado():
            return {"suportado": False, "ligado": False, "erro": "O Wi-Fi próprio dos caixas só existe no Windows."}
        executar = subprocess.run
    try:
        r = executar(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                     capture_output=True, text=True, timeout=TEMPO_POWERSHELL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as erro:
        return {"suportado": True, "ligado": False, "erro": f"PowerShell indisponível: {erro}"[:200]}
    saida = (r.stdout or "").strip().splitlines()
    try:
        dados = json.loads(saida[-1]) if saida else {}
    except ValueError:
        dados = {}
    if not isinstance(dados, dict) or "ligado" not in dados:
        erro = (r.stderr or "").strip().splitlines()
        return {"suportado": True, "ligado": False,
                "erro": ("Este computador não consegue criar o hotspot: " + (erro[-1] if erro else "sem resposta"))[:200]}
    return dados


def ler(executar=None) -> dict:
    return _powershell(_LER, executar)


def ligar(executar=None) -> dict:
    return _powershell(_LIGAR, executar)


def guardar_estado(banco, estado: dict) -> None:
    from src.core import formatacao as fmt
    banco.cfg_set(CHAVE_ESTADO, json.dumps({**estado, "visto_em": fmt.agora()}, ensure_ascii=False))


def estado_guardado(banco) -> dict:
    try:
        dados = json.loads(banco.cfg(CHAVE_ESTADO) or "{}")
    except ValueError:
        dados = {}
    return dados if isinstance(dados, dict) else {}


def descrever(estado: dict) -> str:
    """Texto da tela Caixas da loja."""
    if not estado:
        return "Ainda não verificado. Aguarde um minuto."
    if not estado.get("ligado"):
        return "Desligado. " + (estado.get("erro") or "Tentando ligar de novo em 1 minuto.")
    texto = (f"Ligado: rede \"{estado.get('ssid') or '?'}\", senha \"{estado.get('senha') or '?'}\" "
             f"({int(estado.get('conectados') or 0)} aparelho(s) conectado(s)). No notebook adicional, conecte nessa rede "
             "e marque \"Conectar automaticamente\".")
    if estado.get("sem_desligamento") is False:
        texto += (" Para o Windows não desligar sozinho: Configurações > Rede e Internet > Hotspot móvel > desmarque "
                  "\"Quando nenhum dispositivo estiver conectado, desativar automaticamente\".")
    return texto


class ServicoHotspot:
    """No caixa principal com a opção ligada: confere a cada minuto e religa o hotspot se o Windows desligou."""

    def __init__(self, caminho_banco: str, executar=None, intervalo: float = INTERVALO_SEG):
        self.caminho = caminho_banco
        self._executar = executar
        self._intervalo = intervalo
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.ativo = False

    def iniciar(self) -> None:
        if self._thread is not None:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._rodar, name="hotspot-caixas", daemon=True)
        self._thread.start()
        self.ativo = True

    def parar(self) -> None:
        self._parar.set()
        self.ativo = False
        self._thread = None

    def rodada(self) -> dict | None:
        """Uma conferência: só age com a opção ligada. Devolve o estado visto (ou None quando desligada)."""
        from src.database.conexao import BancoDados
        banco = BancoDados(self.caminho, semear=False)
        try:
            if not banco.cfg_bool(CHAVE_LIGADO, False):
                return None
            estado = ler(self._executar)
            if not estado.get("ligado") and estado.get("suportado", True):
                estado = ligar(self._executar)
                if estado.get("ligado"):
                    log.info("Wi-Fi próprio dos caixas religado.")
            guardar_estado(banco, estado)
            return estado
        finally:
            banco.fechar()

    def _rodar(self) -> None:
        while not self._parar.is_set():
            try:
                self.rodada()
            except Exception:                              # noqa: BLE001 - o serviço não pode cair
                log.exception("Falha ao conferir o Wi-Fi próprio dos caixas.")
            self._parar.wait(self._intervalo)
