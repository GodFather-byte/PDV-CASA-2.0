"""Assistente de impressora: escolhe a impressora certa (Elgin i9 e parecidas), configura o caixa e diz o que está errado.

A impressão do WillPDV já funcionava, mas dependia de a pessoa acertar 4 campos técnicos (modo, conexão, nome, colunas) e de
reiniciar. Aqui ficam as regras do 'assistente': sugerir a impressora, gravar a configuração certa de uma vez, imprimir o teste e
montar o DIAGNÓSTICO (o que está errado e como resolver). Nada aqui imprime sozinho nem apaga nada sem pedir.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

from src.controllers.config_controller import ConfigController
from src.core import formatacao as fmt
from src.hardware import impressoras_so
from src.hardware.impressora_termica import ErroImpressao
from src.hardware.impressoras_so import ImpressoraWindows

# Elgin i9: térmica de 80 mm (48 colunas), ESC/POS, página de código CP850 (ESC t 2), corte parcial. As parecidas seguem o mesmo padrão.
_ELGIN = re.compile(r"elgin|\bi[79]\b", re.I)
PERFIL = {"modo_impressao": "termica", "impressora_termica_conexao": "spooler", "impressora_termica_codepage": "cp850",
          "colunas_fita": 48, "impressora_termica_cortar": "S"}


def _eh_windows() -> bool:
    return sys.platform == "win32"


@dataclass(frozen=True)
class Achado:
    nivel: str        # 'erro' (não imprime), 'aviso' (pode falhar) ou 'ok'
    texto: str
    solucao: str = ""


def sugerir(impressoras: list[ImpressoraWindows]) -> ImpressoraWindows | None:
    """A impressora mais provável do caixa: Elgin/i9 primeiro, depois qualquer térmica, depois a padrão. Nunca uma virtual (PDF/fax)."""
    reais = [i for i in impressoras if not i.virtual]
    for criterio in (lambda i: _ELGIN.search(f"{i.nome} {i.driver}"), lambda i: i.termica_provavel, lambda i: i.padrao):
        achada = next((i for i in reais if criterio(i)), None)
        if achada:
            return achada
    return None


def configurar(banco, nome: str, colunas: int | None = None) -> None:
    """Põe o caixa para imprimir cupom na impressora `nome` do Windows (modo térmica, conexão Windows/RAW, CP850, 48 colunas, corte).

    Vale na hora (as próximas impressões já usam), sem precisar sair do programa. Mantém o que já estava configurado de gaveta e logotipo."""
    nome = (nome or "").strip()
    if not nome:
        raise ErroImpressao("Escolha uma impressora da lista.")
    dados = dict(PERFIL, impressora_termica_endereco=nome)
    if colunas:
        dados["colunas_fita"] = colunas
    ConfigController(banco).salvar_maquina(dados)
    banco.log("impressora_configurada", nome)


def diagnosticar(banco, impressoras: list[ImpressoraWindows] | None = None, spooler: bool | None = None,
                 portas_usb: list[str] | None = None) -> list[Achado]:
    """Tudo que pode impedir o cupom de sair, na ordem em que costuma acontecer. Lista vazia de 'erro' = a configuração está certa."""
    m = ConfigController(banco).maquina()
    if impressoras is None:
        impressoras = impressoras_so.listar_impressoras()
    if spooler is None:
        spooler = impressoras_so.servico_spooler_rodando()
    if portas_usb is None:
        portas_usb = impressoras_so.listar_portas_usb()
    achados: list[Achado] = []
    if (impressoras or _eh_windows()) and not any(i.termica_provavel or _ELGIN.search(f"{i.nome} {i.driver}")
                                                  for i in impressoras if not i.virtual):
        # O caso mais comum: a Elgin i9 nunca foi instalada no Windows (só aparecem PDF, XPS, OneNote...). Sem isso nada imprime.
        if portas_usb:
            achados.append(Achado("erro", f"A Elgin i9 não está instalada no Windows: ela está ligada na porta {portas_usb[0]}, mas sem driver.",
                                  "Toque em 'Instalar Elgin i9 (driver genérico)'. Se o Windows pedir permissão, aceite."))
        else:
            achados.append(Achado("erro", "O Windows não encontrou a Elgin i9: nenhuma impressora de cupom instalada e nada de impressora detectado no cabo USB.",
                                  "Ligue a impressora (luz acesa), troque o cabo/porta USB do computador (sem hub) e toque em Atualizar. Se continuar, instale o driver do site da Elgin."))
    modo, conexao = m["modo_impressao"], m["impressora_termica_conexao"]
    endereco = (m["impressora_termica_endereco"] or "").strip()

    if modo != "termica":
        achados.append(Achado("erro", f"O caixa está em modo '{modo}': os cupons NÃO vão para a impressora.",
                              "Toque em 'Configurar e imprimir teste' para ligar a impressão pela impressora térmica."))
    if conexao == "nenhuma" or (modo == "termica" and not endereco and conexao != "arquivo"):
        achados.append(Achado("erro", "Nenhuma impressora escolhida no caixa.", "Escolha a Elgin i9 na lista e use 'Configurar e imprimir teste'."))
    if spooler is False:
        achados.append(Achado("erro", "O serviço 'Spooler de Impressão' do Windows está parado.",
                              "Abra Serviços (services.msc), inicie 'Spooler de Impressão' e tente de novo."))
    if conexao == "spooler" and endereco:
        achada = next((i for i in impressoras if i.nome.strip().lower() == endereco.lower()), None)
        if impressoras and achada is None:
            achados.append(Achado("erro", f"O Windows não tem nenhuma impressora chamada '{endereco}'.",
                                  "Escolha a impressora na lista (o nome tem de ser igual ao do Windows) ou instale o driver da Elgin i9."))
        elif achada is not None:
            if achada.virtual:
                achados.append(Achado("erro", f"'{achada.nome}' é uma impressora virtual (PDF/fax): não sai papel.", "Escolha a Elgin i9."))
            if achada.pausada:
                achados.append(Achado("erro", f"A fila de '{achada.nome}' está PAUSADA no Windows.", "Use 'Destravar fila do Windows'."))
            if achada.offline:
                achados.append(Achado("erro", f"'{achada.nome}' aparece OFFLINE no Windows (desligada, cabo USB solto ou 'usar impressora offline').",
                                      "Ligue a impressora, confira o cabo USB e, no Windows, desmarque Impressora > 'Usar Impressora Offline'."))
            if achada.trabalhos and not achada.pausada and not achada.offline:
                achados.append(Achado("aviso", f"Há {achada.trabalhos} documento(s) parado(s) na fila do Windows de '{achada.nome}'.",
                                      "Se não estão saindo, use 'Destravar fila do Windows'."))

    fila = banco.um("SELECT COALESCE(SUM(status = 'erro'),0) AS erros, COALESCE(SUM(status = 'pendente'),0) AS pendentes "
                    "FROM fila_impressao WHERE status IN ('pendente','erro')")
    if fila["erros"] or fila["pendentes"]:
        ultimo = banco.valor("SELECT ultimo_erro FROM fila_impressao WHERE status IN ('pendente','erro') AND ultimo_erro IS NOT NULL "
                             "ORDER BY id DESC LIMIT 1")
        achados.append(Achado("aviso" if not fila["erros"] else "erro",
                              f"Fila do PDV: {fila['pendentes']} esperando e {fila['erros']} com erro." + (f" Último erro: {ultimo}" if ultimo else ""),
                              "Corrija o problema acima e reenvie em Utilitários > Fila de impressão."))
    if not any(a.nivel == "erro" for a in achados):
        achados.append(Achado("ok", "Configuração do caixa conferida: nada de errado encontrado."))
    return achados


def relatorio(banco, impressoras: list[ImpressoraWindows] | None = None, spooler: bool | None = None, versao: str = "",
              portas_usb: list[str] | None = None) -> str:
    """O diagnóstico em texto, para copiar e mandar a quem dá suporte."""
    m = ConfigController(banco).maquina()
    if impressoras is None:
        impressoras = impressoras_so.listar_impressoras()
    if spooler is None:
        spooler = impressoras_so.servico_spooler_rodando()
    if portas_usb is None:
        portas_usb = impressoras_so.listar_portas_usb()
    linhas = [f"DIAGNÓSTICO DE IMPRESSÃO — WillPDV {versao}".strip(), f"{fmt.fmt_datahora(fmt.agora())}  ·  sistema: {sys.platform}", "",
              "Configuração desta máquina:",
              f"  modo: {m['modo_impressao']}   conexão: {m['impressora_termica_conexao']}   endereço: {m['impressora_termica_endereco'] or '-'}",
              f"  colunas: {m['colunas_fita']}   página de código: {m['impressora_termica_codepage']}   cortar: {'sim' if m['impressora_termica_cortar'] else 'não'}"
              f"   gaveta: {'sim' if m['impressora_termica_gaveta'] else 'não'}", "",
              f"Spooler de Impressão do Windows: {'rodando' if spooler else 'PARADO' if spooler is False else 'não verificado'}",
              f"Portas USB de impressora detectadas: {', '.join(portas_usb) if portas_usb else 'nenhuma'}",
              f"Impressoras no Windows ({len(impressoras)}):"]
    for i in impressoras:
        linhas.append(f"  - {i.nome}{' [padrão]' if i.padrao else ''}  porta: {i.porta or '-'}  driver: {i.driver or '-'}  "
                      f"situação: {i.situacao}  fila: {i.trabalhos}{'  [virtual]' if i.virtual else ''}")
    if not impressoras:
        linhas.append("  (nenhuma)")
    linhas += ["", "Últimos documentos da fila do PDV:"]
    recentes = banco.todos("SELECT id, criado_em, nome, status, tentativas, ultimo_erro FROM fila_impressao ORDER BY id DESC LIMIT 8")
    linhas += [f"  #{r['id']} {fmt.fmt_datahora(r['criado_em'])[:16]} {r['nome']} — {r['status']}, {r['tentativas']} tentativa(s)"
               + (f" — {r['ultimo_erro']}" if r["ultimo_erro"] else "") for r in recentes] or ["  (nenhum)"]
    linhas += ["", "O que foi encontrado:"]
    for a in diagnosticar(banco, impressoras, spooler, portas_usb):
        marca = {"erro": "[ERRO] ", "aviso": "[AVISO] ", "ok": "[OK] "}[a.nivel]
        linhas.append(f"  {marca}{a.texto}" + (f"\n         Como resolver: {a.solucao}" if a.solucao else ""))
    return "\n".join(linhas)


def destravar_fila(nome: str, limpar: bool = False) -> str:
    """Retoma a fila da impressora no Windows (e, com `limpar`, cancela o que estava preso). Devolve o que foi feito."""
    try:
        impressoras_so.controlar_fila(nome, impressoras_so.CONTROLE_RETOMAR)
        if limpar:
            impressoras_so.controlar_fila(nome, impressoras_so.CONTROLE_LIMPAR)
    except (OSError, AttributeError) as e:
        raise ErroImpressao(str(e)) from e
    return "Fila retomada e esvaziada." if limpar else "Fila retomada."


def instalar_generica(nome: str = "Elgin i9", porta: str | None = None) -> str:
    """Instala no Windows uma impressora "Generic / Text Only" na porta USB da Elgin i9 (a que o Windows criou ao detectá-la).

    É o que dá certo quando o driver do fabricante não está instalado: o PDV manda os comandos ESC/POS direto (modo RAW) e o
    driver genérico só repassa. Usa o instalador de impressoras do próprio Windows (printui). Devolve o nome instalado."""
    if not _eh_windows():
        raise ErroImpressao("A instalação da impressora só existe no Windows.")
    nome = (nome or "").strip() or "Elgin i9"
    if any(i.nome.strip().lower() == nome.lower() for i in impressoras_so.listar_impressoras()):
        return nome                                                             # já instalada: nada a fazer
    porta = porta or next(iter(impressoras_so.listar_portas_usb()), None)
    if not porta:
        raise ErroImpressao("O Windows não detectou nenhuma impressora na USB. Ligue a Elgin i9 (luz acesa), troque o cabo ou a porta USB do "
                            "computador e tente de novo.")
    inf = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "inf", "ntprint.inf")
    comando = ["rundll32", "printui.dll,PrintUIEntry", "/if", "/b", nome, "/f", inf, "/r", porta, "/m", "Generic / Text Only"]
    try:
        subprocess.run(comando, capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        raise ErroImpressao(f"Não consegui rodar o instalador de impressoras do Windows ({e}).") from e
    if not any(i.nome.strip().lower() == nome.lower() for i in impressoras_so.listar_impressoras()):
        raise ErroImpressao("O Windows não instalou a impressora. Feche o PDV, abra-o de novo com 'Executar como administrador' e repita, ou "
                            "instale pelo Windows: Configurações > Impressoras > Adicionar > impressora local, porta "
                            f"{porta}, fabricante Generic, modelo 'Generic / Text Only', nome '{nome}'.")
    return nome
