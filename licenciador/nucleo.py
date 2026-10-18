"""Regras do WillPDV Licenças (sem tela): chave de segurança, emissão (mensal, permanente, teste) e histórico.

Usa exatamente o mesmo código e o mesmo arquivo de chave de `tools/gerar_licenca.py` (`~/.pdv-casa/licenca_privada.key`),
então os dois conversam. A chave privada NUNCA vai para o repositório nem para o PC do cliente.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.core import ed25519, licenca
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

VERSAO = "1.1.0"
MAX_MESES = 60
MAX_DIAS_TESTE = 90
TIPOS = ("mensal", "permanente", "teste")
ROTULO = {"mensal": "Mensal", "permanente": "Permanente", "teste": "Teste"}


class ErroLicenciador(ErroNegocio):
    """Algo que o operador pode corrigir (mensagem já em português, pronta para mostrar na tela)."""


# ------------------------------------------------------------------ pastas
def arquivo_chave() -> Path:
    return Path(os.environ.get("PDV_LICENCA_CHAVE") or Path.home() / ".pdv-casa" / "licenca_privada.key")


def arquivo_historico() -> Path:
    base = os.environ.get("WILLLICENCAS_DADOS") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WillPDV-Licencas"
    return Path(base) / "historico.json"


# ------------------------------------------------------------------- chave
@dataclass(frozen=True)
class EstadoChave:
    existe: bool
    legivel: bool = False
    confere: bool = False        # a chave pública derivada é a mesma que está dentro do PDV (CHAVE_PUBLICA_HEX)
    publica_hex: str = ""
    mensagem: str = ""

    @property
    def pronta(self) -> bool:
        return self.existe and self.legivel and self.confere


def _ler_semente(arquivo: Path) -> bytes:
    try:
        semente = bytes.fromhex(arquivo.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        raise ErroLicenciador(f"Não consegui ler a chave de segurança em {arquivo}. Importe o arquivo certo na aba Chave.") from None
    if len(semente) != 32:
        raise ErroLicenciador("A chave de segurança deve ter 64 caracteres (letras e números). O arquivo está diferente do esperado.")
    return semente


def estado_chave(arquivo: Path | None = None) -> EstadoChave:
    arquivo = arquivo or arquivo_chave()
    if not arquivo.exists():
        return EstadoChave(False, mensagem="Ainda não há chave de segurança neste computador. Importe a sua (se já tem) ou crie uma na aba Chave.")
    try:
        publica = ed25519.chave_publica(_ler_semente(arquivo)).hex()
    except ErroLicenciador as e:
        return EstadoChave(True, mensagem=str(e))
    if publica != licenca.CHAVE_PUBLICA_HEX:
        return EstadoChave(True, True, False, publica,
                           "Esta chave NÃO é a do PDV: os caixas recusariam as licenças. Importe a chave certa (a que gerou o PDV).")
    return EstadoChave(True, True, True, publica, "Chave de segurança conferida: combina com a do PDV.")


def criar_chave(arquivo: Path | None = None) -> str:
    """Cria a chave privada se AINDA não existir (nunca sobrescreve). Devolve a chave pública em hexadecimal."""
    arquivo = arquivo or arquivo_chave()
    if arquivo.exists():
        raise ErroLicenciador("Já existe uma chave. Não vou sobrescrever: trocar a chave invalida todas as licenças já emitidas.")
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    semente = secrets.token_bytes(32)
    arquivo.write_text(semente.hex() + "\n", encoding="ascii")
    try:
        os.chmod(arquivo, 0o600)
    except OSError:
        pass
    return ed25519.chave_publica(semente).hex()


def importar_chave(origem: Path, destino: Path | None = None, substituir: bool = False) -> EstadoChave:
    """Copia a chave de `origem` para o lugar padrão. Se já houver uma, só troca com `substituir` (e guarda a antiga em .bak)."""
    destino = destino or arquivo_chave()
    _ler_semente(Path(origem))                                     # recusa arquivo que não é uma chave
    if destino.exists() and Path(origem).resolve() != destino.resolve():
        if not substituir:
            raise ErroLicenciador("Já existe uma chave neste computador. Confirme a substituição para trocar (a atual vira um .bak).")
        shutil.copy2(destino, destino.with_suffix(".key.bak"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    if Path(origem).resolve() != destino.resolve():
        shutil.copy2(origem, destino)
    try:
        os.chmod(destino, 0o600)
    except OSError:
        pass
    return estado_chave(destino)


def backup_chave(destino: Path, arquivo: Path | None = None) -> Path:
    arquivo = arquivo or arquivo_chave()
    _ler_semente(arquivo)
    destino = Path(destino)
    if destino.is_dir():
        destino = destino / "licenca_privada-backup.key"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(arquivo, destino)
    return destino


# ------------------------------------------------------------------ emissão
@dataclass(frozen=True)
class Emitida:
    codigo: str
    loja: str
    tipo: str
    quantidade: int
    emitida_em: date
    expira_em: date

    @property
    def descricao(self) -> str:
        if self.tipo == "permanente":
            return "Permanente"
        return f"Mensal ({self.quantidade} {'mês' if self.quantidade == 1 else 'meses'})" if self.tipo == "mensal" \
            else f"Teste ({self.quantidade} dias)"


def validade(tipo: str, quantidade: int, hoje: date | None = None) -> date:
    """Último dia de validade. Mensal: `quantidade` meses de calendário (1 mês a partir de 09/10 vai até 09/11)."""
    hoje = hoje or date.fromisoformat(fmt.hoje())
    if tipo == "permanente":
        return date.fromordinal(hoje.toordinal() + licenca.MAX_DIAS)
    if tipo == "mensal":
        if not 1 <= quantidade <= MAX_MESES:
            raise ErroLicenciador(f"Informe de 1 a {MAX_MESES} meses.")
        return date.fromisoformat(fmt.somar_meses(hoje.isoformat(), quantidade))
    if tipo == "teste":
        if not 1 <= quantidade <= MAX_DIAS_TESTE:
            raise ErroLicenciador(f"O teste vai de 1 a {MAX_DIAS_TESTE} dias.")
        return date.fromordinal(hoje.toordinal() + quantidade)
    raise ErroLicenciador("Escolha o tipo de licença.")


def emitir(loja: str, tipo: str, quantidade: int = 1, arquivo: Path | None = None, hoje: date | None = None) -> Emitida:
    loja = " ".join((loja or "").split())
    if not loja:
        raise ErroLicenciador("Informe o nome (chave) da loja. É o mesmo que fica em Configurações do PDV.")
    hoje = hoje or date.fromisoformat(fmt.hoje())
    expira = validade(tipo, quantidade, hoje)
    estado = estado_chave(arquivo)
    if not estado.pronta:
        raise ErroLicenciador(estado.mensagem)
    semente = _ler_semente(arquivo or arquivo_chave())
    dias = (expira - hoje).days
    codigo = licenca.gerar_licenca(semente, loja, dias, hoje)
    lic = licenca.ler_licenca(codigo)                              # confere de volta, com a chave pública do PDV
    return Emitida(codigo, lic["loja"], tipo, quantidade if tipo != "permanente" else 0, lic["emitida_em"], lic["expira_em"])


def conferir(codigo: str, hoje: date | None = None) -> dict:
    """Assinatura + prazo de um código já emitido. Levanta ErroLicenciador se não for um código do PDV."""
    try:
        lic = licenca.ler_licenca(codigo)
    except licenca.LicencaInvalida as e:
        raise ErroLicenciador(str(e)) from None
    hoje = hoje or date.fromisoformat(fmt.hoje())
    dias = (lic["expira_em"] - hoje).days
    permanente = (lic["expira_em"] - lic["emitida_em"]).days >= licenca.MAX_DIAS - 1
    situacao = ("Permanente" if permanente else "Vencida" if dias < 0 else "Vence hoje" if dias == 0
                else f"Válida: faltam {dias} dia{'s' if dias != 1 else ''}")
    return {**lic, "dias": dias, "permanente": permanente, "situacao": situacao}


# ---------------------------------------------------------------- histórico
class Historico:
    """Lista das licenças emitidas (um arquivo JSON local), para saber quem vence e renovar com um clique."""

    def __init__(self, arquivo: Path | None = None):
        self.arquivo = arquivo or arquivo_historico()

    def todas(self) -> list[dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return [d for d in dados if isinstance(d, dict) and d.get("codigo")]
        except (OSError, ValueError):
            return []

    def _gravar(self, itens: list[dict]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = self.arquivo.with_suffix(".tmp")
        provisorio.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
        provisorio.replace(self.arquivo)                           # troca inteira: queda de energia não deixa arquivo pela metade

    def adicionar(self, e: Emitida) -> None:
        itens = self.todas()
        itens.append({"loja": e.loja, "tipo": e.tipo, "quantidade": e.quantidade, "emitida_em": e.emitida_em.isoformat(),
                      "expira_em": e.expira_em.isoformat(), "codigo": e.codigo})
        self._gravar(itens)

    def remover(self, codigo: str) -> None:
        self._gravar([d for d in self.todas() if d["codigo"] != codigo])

    def lojas(self) -> list[str]:
        return sorted({d["loja"] for d in self.todas()}, key=str.casefold)

    def situacao_das_lojas(self, hoje: date | None = None) -> list[dict]:
        """Uma linha por loja: a licença mais nova dela, com os dias que faltam. Quem vence primeiro aparece primeiro."""
        hoje = hoje or date.fromisoformat(fmt.hoje())
        ultima: dict[str, dict] = {}
        for d in self.todas():
            chave = d["loja"].casefold()
            if chave not in ultima or (d["expira_em"], d["emitida_em"]) > (ultima[chave]["expira_em"], ultima[chave]["emitida_em"]):
                ultima[chave] = d
        linhas = []
        for d in ultima.values():
            expira = date.fromisoformat(d["expira_em"])
            dias = (expira - hoje).days
            permanente = d["tipo"] == "permanente"
            linhas.append({**d, "dias": dias, "permanente": permanente,
                           "situacao": "Permanente" if permanente else "Vencida" if dias < 0 else "Vence hoje" if dias == 0
                           else f"Vence em {dias} dia{'s' if dias != 1 else ''}" if dias <= licenca.AVISO_DIAS else "Em dia"})
        return sorted(linhas, key=lambda x: (x["permanente"], x["dias"]))


# ------------------------------------------------------------------ vencimentos
def resumo_vencimentos(historico: "Historico", hoje: date | None = None) -> dict:
    """Lojas vencidas e as que vencem dentro do prazo de aviso do PDV, para avisar assim que o programa abre."""
    vencidas, vencendo = [], []
    for linha in historico.situacao_das_lojas(hoje):
        if linha["permanente"]:
            continue
        if linha["dias"] < 0:
            vencidas.append(linha["loja"])
        elif linha["dias"] <= licenca.AVISO_DIAS:
            vencendo.append((linha["loja"], linha["dias"]))
    return {"vencidas": vencidas, "vencendo": vencendo}


def texto_do_aviso(resumo: dict) -> str:
    """Frase curta para a faixa do topo; vazia quando não há nada a renovar."""
    partes = []
    if resumo["vencidas"]:
        n = len(resumo["vencidas"])
        partes.append(f"{n} licença{'s' if n != 1 else ''} vencida{'s' if n != 1 else ''}: " + ", ".join(resumo["vencidas"]))
    if resumo["vencendo"]:
        itens = ", ".join(f"{loja} ({'hoje' if dias == 0 else f'{dias} dia' + ('s' if dias != 1 else '')})"
                          for loja, dias in resumo["vencendo"])
        partes.append("vencendo em breve: " + itens)
    return ("⚠ " + "; ".join(partes) + ". Veja a aba Lojas e vencimentos.") if partes else ""


# ----------------------------------------------------------------- backup
PASTA_BACKUP = "WillPDV-Licencas"          # subpasta criada dentro da pasta escolhida (por exemplo, a do Google Drive)
COPIAS_DO_HISTORICO = 30                   # quantas cópias diárias manter; as mais antigas saem


class Configuracao:
    """Preferências do programa (um JSON ao lado do histórico): pasta do backup e se o backup é automático."""

    def __init__(self, arquivo: Path | None = None):
        self.arquivo = arquivo or arquivo_historico().with_name("config.json")

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def _gravar(self, dados: dict) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = self.arquivo.with_suffix(".tmp")
        provisorio.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        provisorio.replace(self.arquivo)

    @property
    def pasta_backup(self) -> Path | None:
        texto = self._ler().get("pasta_backup")
        return Path(texto) if texto else None

    @property
    def backup_automatico(self) -> bool:
        return bool(self._ler().get("backup_automatico", True))

    @property
    def ultimo_backup(self) -> str:
        return str(self._ler().get("ultimo_backup", ""))

    def definir(self, **campos) -> None:
        dados = self._ler()
        for chave, valor in campos.items():
            dados[chave] = str(valor) if isinstance(valor, Path) else valor
        self._gravar(dados)


def pastas_do_google_drive() -> list[Path]:
    """Pastas do aplicativo Google Drive para computador que existem neste PC (ele sincroniza a pasta sozinho)."""
    home = Path.home()
    candidatas = [home / "Google Drive", home / "My Drive", home / "Meu Drive", home / "Google Drive" / "Meu Drive",
                  home / "Google Drive" / "My Drive", Path("G:/Meu Drive"), Path("G:/My Drive")]
    achadas = []
    for pasta in candidatas:
        try:
            if pasta.is_dir() and pasta not in achadas:
                achadas.append(pasta)
        except OSError:
            continue
    return achadas


def _pasta_do_backup(pasta: Path) -> Path:
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise ErroLicenciador(f"A pasta de backup não existe: {pasta}\nSe for o Google Drive, confira se ele está aberto neste computador.")
    destino = pasta / PASTA_BACKUP
    try:
        destino.mkdir(exist_ok=True)
    except OSError as e:
        raise ErroLicenciador(f"Não consegui criar a pasta de backup em {pasta}: {e}") from None
    return destino


def _gravar_inteiro(destino: Path, conteudo: bytes) -> None:
    """Grava num arquivo temporário e troca de uma vez: o Drive nunca sincroniza um arquivo pela metade."""
    provisorio = destino.with_name(f".{destino.name}.tmp")
    try:
        provisorio.write_bytes(conteudo)
        provisorio.replace(destino)
    finally:
        provisorio.unlink(missing_ok=True)


def backup_historico(pasta: Path, historico: "Historico", hoje: date | None = None, manter: int = COPIAS_DO_HISTORICO) -> Path:
    """Copia o histórico para `pasta/WillPDV-Licencas/historico-AAAA-MM-DD.json` (uma cópia por dia, as mais antigas saem)."""
    if not historico.todas():
        raise ErroLicenciador("Ainda não há licenças no histórico para guardar.")
    hoje = hoje or date.fromisoformat(fmt.hoje())
    destino = _pasta_do_backup(pasta)
    arquivo = destino / f"historico-{hoje.isoformat()}.json"
    try:
        _gravar_inteiro(arquivo, historico.arquivo.read_bytes())
        copias = sorted(destino.glob("historico-????-??-??.json"))
        for velha in copias[:-manter] if manter > 0 else []:
            velha.unlink(missing_ok=True)
    except OSError as e:
        raise ErroLicenciador(f"Não consegui gravar o backup do histórico: {e}") from None
    return arquivo


def backup_chave_protegido(pasta: Path, senha: str, arquivo: Path | None = None) -> Path:
    """Cópia da chave privada CRIPTOGRAFADA com senha. Só assim ela pode ir para um serviço de nuvem como o Google Drive."""
    try:
        from src.core import backup_seguro
    except ImportError:
        raise ErroLicenciador("Faltou o componente de criptografia neste programa; use a cópia comum da chave em um pendrive.") from None
    arquivo = arquivo or arquivo_chave()
    _ler_semente(arquivo)
    try:
        backup_seguro.validar_senha(senha)
    except ValueError as e:
        raise ErroLicenciador(str(e)) from None
    destino = _pasta_do_backup(pasta) / "licenca_privada.key.pdvbkp"
    try:
        backup_seguro.criptografar(arquivo, destino, senha)
    except OSError as e:
        raise ErroLicenciador(f"Não consegui gravar o backup da chave: {e}") from None
    return destino


def restaurar_chave_protegida(origem: Path, senha: str, destino: Path | None = None, substituir: bool = False) -> EstadoChave:
    """Abre o backup criptografado da chave e instala como chave deste computador (mesmas regras de `importar_chave`)."""
    from src.core import backup_seguro
    with tempfile.TemporaryDirectory(prefix="willlic_") as pasta:
        aberto = Path(pasta) / "licenca_privada.key"
        try:
            backup_seguro.descriptografar(origem, aberto, senha)
        except ValueError as e:
            raise ErroLicenciador(str(e)) from None
        except OSError as e:
            raise ErroLicenciador(f"Não consegui ler o backup: {e}") from None
        return importar_chave(aberto, destino, substituir)


def restaurar_historico(origem: Path, historico: "Historico") -> int:
    """Troca o histórico por um backup (o atual vira .bak). Devolve quantas licenças voltaram."""
    try:
        dados = json.loads(Path(origem).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErroLicenciador("Esse arquivo não é um backup de histórico válido.") from None
    itens = [d for d in dados if isinstance(d, dict) and d.get("codigo")] if isinstance(dados, list) else []
    if not itens:
        raise ErroLicenciador("Esse backup não tem nenhuma licença.")
    for d in itens:
        try:
            licenca.ler_licenca(d["codigo"])
        except licenca.LicencaInvalida:
            raise ErroLicenciador("Esse backup tem um código de licença que não confere com a chave do PDV.") from None
    if historico.arquivo.exists():
        shutil.copy2(historico.arquivo, historico.arquivo.with_suffix(".json.bak"))
    historico._gravar(itens)
    return len(itens)


# -------------------------------------------------------------- mensagem
def mensagem_para_o_cliente(e: Emitida) -> str:
    """Texto pronto para mandar (WhatsApp, e-mail...) com o código e como ativar."""
    validade_txt = "sem vencimento" if e.tipo == "permanente" else f"válida até {e.expira_em.strftime('%d/%m/%Y')}"
    return (f"Licença do WillPDV — {e.loja} ({validade_txt}).\n\n{e.codigo}\n\n"
            "Como ativar: na tela de entrada do WillPDV, toque em \"Código de licença...\", cole o código inteiro e confirme.")
