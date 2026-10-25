"""Edição do programa: o mesmo código gera o WillPDV (completo, nasceu boate) e o E&A Superações (só adega).

A edição define a marca (nome, ícone, logotipo), a pasta dos dados no Windows e, na adega, o perfil de operação aplicado na
primeira entrada, as configurações que ficam sempre com o mesmo valor (sem mesas, garotas, portaria, rodízio nem pré-pago) e
o que some das Configurações e do menu por não fazer sentido numa adega.

Qual edição roda: a variável PDV_EDICAO; no executável, o arquivo `edicao.txt` ao lado dele (gravado pelo build); senão o
WillPDV. No código-fonte: `python -m src.app --edicao ea_superacoes` (ou `iniciar_ea_superacoes.bat`).
Executável e instalador de cada edição: `python build_pdv.py --edicao ea_superacoes` (WillPDV sem a opção).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PADRAO = "willpdv"
VARIAVEL = "PDV_EDICAO"
ARQUIVO = "edicao.txt"

# Configurações da casa noturna e das mesas/comandas: numa edição sem elas, não aparecem em Configurações.
CHAVES_CASA_NOTURNA = frozenset({
    "posicao_padrao", "num_mesas", "num_comandas", "cobra_servico_mesa", "cobra_servico_comanda", "servico_pct",
    "controle_garcom", "comissao_garcom_pct", "tempo_inatividade_min", "pergunta_pessoas", "painel_mesas_fixo",
    "painel_mostra_garotas", "consumacao_minima", "limite_comanda", "consumacao_minima_de", "consumacao_minima_ate",
    "exigir_senha_comissao", "codigo_comissao", "comissao_em_pontos", "comissao_valor_ponto", "comissao_paga_do_caixa",
    "imprimir_saida_ao_pagar", "codigo_saida", "comissao_na_linha", "imprimir_via_comissao", "comissao_pede_shows",
    "show_valores", "valor_rodizio_pessoa",
})


@dataclass(frozen=True)
class Edicao:
    chave: str
    nome: str                          # nos títulos e nas mensagens
    marca: str                         # o texto grande no alto do menu
    icone: str                         # arquivo em instalador/ (no executável, junto do programa)
    logotipo: str | None               # imagem no alto do menu (None: só o texto da marca)
    pasta_dados: str                   # %LOCALAPPDATA%\<pasta>: cada edição com os seus dados
    perfil: str | None = None          # perfil de operação aplicado na primeira entrada (PerfilController)
    fixas: dict = field(default_factory=dict)          # configuração -> valor que nunca muda nesta edição
    ocultas: frozenset = frozenset()                   # configurações que não aparecem em Configurações
    menu_oculto: frozenset = frozenset()               # botões do menu principal que não aparecem
    sufixo_titulo: str = ""            # complemento do título da janela principal
    titulo_entrada: str = "Entrada"    # título da tela de entrada (depois do nome)
    executavel: str = "WillPDV"        # nome do .exe e da pasta em dist/ (sem acento nem &: o instalador usa no cmd)
    script_instalador: str = "WillPDV.iss"     # em instalador/ (Inno Setup)

    def fora_das_configuracoes(self) -> frozenset:
        return self.ocultas | frozenset(self.fixas)


EDICOES = {
    "willpdv": Edicao("willpdv", "WillPDV", "WILLPDV", "willpdv.ico", None, "WILL-PDV",
                      sufixo_titulo=" • Qt piloto", titulo_entrada="Entrada Qt"),
    "ea_superacoes": Edicao(
        "ea_superacoes", "E&A Superações", "E&A SUPERAÇÕES", "ea-superacoes.ico", "ea-superacoes-logo.png",
        "EA-SUPERACOES", perfil="adega",
        fixas={"usar_mesas": "N", "usar_garotas": "N", "usar_portaria": "N", "usar_rodizio": "N", "usar_prepago": "N"},
        ocultas=CHAVES_CASA_NOTURNA, menu_oculto=frozenset({"cozinha"}),
        executavel="EASuperacoes", script_instalador="EASuperacoes.iss"),
}


def _do_arquivo() -> str:
    """No executável, a edição gravada pelo build ao lado do .exe (ou dentro do pacote)."""
    if not getattr(sys, "frozen", False):
        return ""
    for pasta in (Path(sys.executable).resolve().parent, Path(getattr(sys, "_MEIPASS", "") or ".")):
        arquivo = pasta / ARQUIVO
        if arquivo.is_file():
            return arquivo.read_text(encoding="utf-8").strip()
    return ""


def atual() -> Edicao:
    """A edição em uso. Nome desconhecido é erro: rodar a edição errada abriria a pasta de dados de outra."""
    chave = (os.environ.get(VARIAVEL) or _do_arquivo() or PADRAO).strip().lower()
    if chave not in EDICOES:
        raise ValueError(f"Edição desconhecida: {chave!r}. Use uma de: {', '.join(EDICOES)}.")
    return EDICOES[chave]


def pasta_recursos() -> Path:
    """Onde ficam o ícone e o logotipo: no executável, dentro do pacote; no código-fonte, a pasta instalador/."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).resolve().parent)
    return Path(__file__).resolve().parents[2] / "instalador"


def preparar(banco, operador_id: int | None = None) -> list[dict]:
    """Deixa o banco do jeito da edição. Na primeira entrada desta edição aplica o perfil dela (o que o dono ajustar depois
    continua); as configurações fixas voltam ao valor da edição a cada entrada. Devolve o que o perfil mudou."""
    ed = atual()
    mudancas: list[dict] = []
    if ed.perfil and banco.cfg("edicao") != ed.chave:
        from src.controllers.perfil_controller import PerfilController
        mudancas = PerfilController(banco, operador_id).aplicar(ed.perfil)
        banco.cfg_set("edicao", ed.chave)
    for chave, valor in ed.fixas.items():
        if banco.cfg(chave) != valor:
            banco.cfg_set(chave, valor)
    return mudancas
