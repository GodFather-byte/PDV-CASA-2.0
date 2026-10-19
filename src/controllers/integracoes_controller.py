"""Preparação local de iFood e NFC-e: sem conexão externa ou emissão fiscal."""
from __future__ import annotations

from typing import TypedDict

from src.controllers.perfil_controller import PERFIS
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.database.sementes import CONFIG_PADRAO


class SituacaoIntegracao(TypedDict):
    estado: str
    disponivel_no_perfil: bool
    operacional: bool
    pendencias: list[str]


class IntegracoesController:
    def __init__(self, banco: BancoDados):
        self.banco = banco

    def situacao(self, modulo: str) -> SituacaoIntegracao:
        if modulo not in ("ifood", "nfce"):
            raise ErroNegocio(f"Integração desconhecida: {modulo}.")
        chave = f"integracao_{modulo}_estado"
        estado = self.banco.cfg(chave, CONFIG_PADRAO[chave])
        if estado not in ("desativado", "preparacao"):
            raise ErroNegocio(f"Estado inválido da integração {modulo}: {estado}.")
        perfil = self.banco.cfg("perfil_operacao", CONFIG_PADRAO["perfil_operacao"])
        if perfil not in PERFIS:
            raise ErroNegocio(f"Perfil desconhecido: {perfil}.")
        disponivel = perfil != "boate"
        pendencias = []
        if not disponivel:
            pendencias.append("Boate está fora desta etapa de integração.")
        if estado == "desativado":
            pendencias.append("Módulo desativado; a preparação é opcional por loja.")
        if modulo == "ifood":
            if not self.banco.cfg_bool("usar_delivery", False):
                pendencias.append("Habilitar o delivery manual nas configurações de módulos.")
            pendencias.extend([
                "Obter acesso de desenvolvedor ao iFood e uma loja de teste.",
                "Implementar o conector, o vínculo de produtos e o tratamento de pedidos duplicados.",
                "Validar pedidos, pagamentos e cancelamentos em testes e homologar no iFood.",
                "Obter autorização de cada loja antes de operar em produção.",
            ])
        else:
            loja = self.banco.um("SELECT * FROM loja WHERE id = 1")
            if loja is None:
                raise ErroNegocio("Cadastro da loja não encontrado.")
            if (loja["uf"] or "").strip().upper() != "SP":
                pendencias.append("Esta primeira etapa fiscal é destinada a lojas em SP.")
            for campo, nome in (("cnpj", "CNPJ"), ("ie", "inscrição estadual")):
                if not (loja[campo] or "").strip():
                    pendencias.append(f"Informar {nome} no cadastro da loja e validar com o contador.")
            if self.banco.cfg("nfce_regime_tributario", "nao_definido") == "nao_definido":
                pendencias.append("Confirmar o regime tributário com o contador.")
            pendencias.extend([
                "Escolher o provedor fiscal e confirmar custos e suporte à NFC-e em SP.",
                "Validar credenciamento, certificado digital e CSC conforme os requisitos aplicáveis.",
                "Validar a tributação dos produtos e os dados do emitente com o contador.",
                "Implementar emissão, consulta, cancelamento, XML e documento auxiliar.",
                "Definir o tratamento de falhas de internet e homologar antes da produção.",
            ])
        return {"estado": estado, "disponivel_no_perfil": disponivel,
                "operacional": False, "pendencias": pendencias}

    def resumo(self) -> str:
        linhas = ["PREPARAÇÃO APENAS: não recebe pedidos do iFood e não emite notas fiscais.",
                  "Nenhum serviço é contratado e nenhum dado é enviado por esta preparação.", ""]
        for modulo, nome in (("ifood", "iFood"), ("nfce", "NFC-e modelo 65 — SP")):
            situacao = self.situacao(modulo)
            estado = "Desativado" if situacao["estado"] == "desativado" else "Em preparação"
            linhas.append(f"{nome}: {estado} — operação bloqueada.")
            linhas.extend(f"- {pendencia}" for pendencia in situacao["pendencias"])
            linhas.append("")
        linhas.append("O cupom atual continua NÃO FISCAL. Obrigações fiscais devem ser avaliadas com o contador.")
        return "\n".join(linhas)
