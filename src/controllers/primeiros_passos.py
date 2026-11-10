"""Primeiros passos da instalação: o que já está pronto nesta loja e o que ainda falta.

Só lê o estado gravado (licença, cadastro da casa, impressora, produtos, nuvem, backup). A única coisa que grava é a
marca de que o tipo de negócio foi escolhido, para o passo não voltar a aparecer como pendente.
"""
from __future__ import annotations

from src.controllers.config_controller import ConfigController
from src.controllers.perfil_controller import PERFIS, PerfilController
from src.core import edicao, licenca

CHAVE_PERFIL_ESCOLHIDO = "primeiros_passos_perfil"


class PrimeirosPassos:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id
        self.config = ConfigController(banco)

    # ------------------------------------------------------------- consulta
    def passos(self) -> list[dict]:
        """[{chave, titulo, feito, detalhe, essencial}], na ordem em que a instalação costuma andar."""
        passos = [self._licenca(), self._loja()]
        if not edicao.atual().perfil_fixo():               # edição com perfil fixo (Will Adega) não escolhe tipo de negócio
            passos.append(self._perfil())
        passos += [self._impressora(), self._produtos(), self._nuvem(), self._backup()]
        return passos

    def resumo(self) -> dict:
        passos = self.passos()
        feitos = sum(p["feito"] for p in passos)
        return {"feitos": feitos, "total": len(passos), "concluido": feitos == len(passos),
                "essenciais_pendentes": [p["chave"] for p in passos if p["essencial"] and not p["feito"]]}

    def escolher_perfil(self, perfil: str) -> list[dict]:
        """Aplica o tipo de negócio pelas regras do PerfilController e marca o passo como feito. Devolve o que mudou."""
        mudancas = PerfilController(self.banco, self.operador_id).aplicar(perfil)
        self.banco.cfg_set(CHAVE_PERFIL_ESCOLHIDO, "S")
        return mudancas

    # --------------------------------------------------------------- passos
    @staticmethod
    def _passo(chave, titulo, feito, detalhe, essencial=False) -> dict:
        return {"chave": chave, "titulo": titulo, "feito": bool(feito), "detalhe": detalhe, "essencial": essencial}

    def _licenca(self) -> dict:
        estado = licenca.estado(self.banco)
        if estado.situacao == "desativada":
            return self._passo("licenca", "Licença", True, "Não é exigida neste ambiente.")
        if estado.bloqueia:
            return self._passo("licenca", "Licença", False,
                               estado.mensagem or "Ative na tela de entrada, em \"Ativar licença ou instalar loja\".", True)
        validade = f"Válida até {estado.expira_em.strftime('%d/%m/%Y')}." if estado.expira_em else "Ativa."
        return self._passo("licenca", "Licença", True, validade + (" " + estado.mensagem if estado.avisa else ""))

    def _loja(self) -> dict:
        feito = self.config.loja_cadastrada()
        return self._passo("loja", "Nome e dados da casa", feito,
                           self.config.nome_loja() if feito else "O nome sai no cabeçalho de todos os comprovantes.", True)

    def _perfil(self) -> dict:
        atual = PerfilController(self.banco).atual()
        feito = self.banco.cfg(CHAVE_PERFIL_ESCOLHIDO) == "S"
        return self._passo("perfil", "Tipo de negócio", feito,
                           (f"{PERFIS[atual][0]}." if feito
                            else f"Hoje está como {PERFIS[atual][0]}. Escolher o tipo liga os módulos certos de uma vez."))

    def _impressora(self) -> dict:
        maquina = self.config.maquina()
        modo = (maquina["modo_impressao"] or "tela").strip().lower()
        feito = modo != "tela"
        return self._passo("impressora", "Impressora de cupom", feito,
                           f"Modo de impressão: {modo}." if feito
                           else "Os comprovantes estão saindo só na tela. O assistente encontra e testa a impressora.")

    def _produtos(self) -> dict:
        quantidade = self.banco.valor("SELECT COUNT(*) FROM produtos WHERE ativo = 1") or 0
        return self._passo("produtos", "Produtos", quantidade > 0,
                           f"{quantidade} produto(s) cadastrado(s)." if quantidade
                           else "Importe a planilha da loja ou cadastre os primeiros produtos.")

    def _nuvem(self) -> dict:
        ligada = bool(self.banco.cfg("api_url").strip() and self.banco.cfg("api_token").strip())
        painel = self.banco.cfg_bool("painel_dono", False)
        if not ligada:
            detalhe = "Cole o código de instalação (WILL1-...) na tela de entrada: nuvem, painel e licença se configuram sozinhos."
        elif painel:
            detalhe = "Conectada, com o painel do dono no celular ligado."
        else:
            detalhe = "Conectada. O painel do dono está desligado: ligue em Configurações > Conexão com a nuvem."
        return self._passo("nuvem", "Nuvem e painel do dono", ligada and painel, detalhe)

    def _backup(self) -> dict:
        pasta = self.banco.cfg("backup_externo_pasta").strip()
        return self._passo("backup", "Backup fora deste computador", bool(pasta),
                           f"Cópias cifradas em {pasta}." if pasta
                           else "Sem cópia externa, um defeito no computador pode levar o histórico da loja.")
