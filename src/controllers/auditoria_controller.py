"""Consulta administrativa dos eventos estruturados, sem alterar o log legado."""
from __future__ import annotations

import json
from datetime import datetime

from src.controllers.acesso_controller import AcessoController, Operador
from src.core.erros import ErroPermissao, ErroValidacao


class AuditoriaController:
    def __init__(self, banco, operador: Operador | None):
        self.banco = banco
        self.operador = operador

    def _exigir_acesso(self) -> None:
        linha = self.banco.um("SELECT * FROM operadores WHERE id = ? AND ativo = 1",
                              (self.operador.id if self.operador else None,))
        if linha is None or linha["nivel"] != 4:
            raise ErroPermissao("A auditoria estruturada é exclusiva do administrador.")
        acesso = AcessoController(self.banco)
        acesso.exigir(acesso._operador(linha), "rel_auditoria")

    @staticmethod
    def _data(valor: str | None, final: bool = False) -> str | None:
        if valor is None or valor == "":
            return None
        if not isinstance(valor, str):
            raise ErroValidacao("Informe a data ISO: AAAA-MM-DD ou AAAA-MM-DD HH:MM:SS.")
        formato = "%Y-%m-%d" if len(valor) == 10 else "%Y-%m-%d %H:%M:%S"
        try:
            data = datetime.strptime(valor, formato)
        except ValueError:
            raise ErroValidacao("Informe a data ISO: AAAA-MM-DD ou AAAA-MM-DD HH:MM:SS.") from None
        if data.strftime(formato) != valor:
            raise ErroValidacao("Informe a data ISO: AAAA-MM-DD ou AAAA-MM-DD HH:MM:SS.")
        if len(valor) == 10:
            return valor + (" 23:59:59" if final else " 00:00:00")
        return valor

    def listar(self, inicio: str | None = None, fim: str | None = None,
               acao: str | None = None, limite: int = 100, offset: int = 0) -> list[dict]:
        """Mais recentes primeiro; datas inclusivas; páginas de 1 a 500 eventos."""
        self._exigir_acesso()
        if (type(limite) is not int or not 1 <= limite <= 500
                or type(offset) is not int or offset < 0):
            raise ErroValidacao("Use limite inteiro entre 1 e 500 e offset inteiro não negativo.")
        inicio, fim = self._data(inicio), self._data(fim, final=True)
        if inicio and fim and inicio > fim:
            raise ErroValidacao("A data inicial não pode ser posterior à final.")
        onde, parametros = [], []
        if inicio:
            onde.append("quando >= ?")
            parametros.append(inicio)
        if fim:
            onde.append("quando <= ?")
            parametros.append(fim)
        if acao is not None:
            if not isinstance(acao, str) or not acao or len(acao) > 80:
                raise ErroValidacao("Informe uma ação válida.")
            onde.append("acao = ?")
            parametros.append(acao)
        sql = "SELECT * FROM auditoria_eventos"
        if onde:
            sql += " WHERE " + " AND ".join(onde)
        sql += " ORDER BY quando DESC, id DESC LIMIT ? OFFSET ?"
        eventos = []
        for linha in self.banco.todos(sql, (*parametros, limite, offset)):
            evento = dict(linha)
            for campo in ("antes", "depois"):
                evento[campo] = json.loads(evento[campo]) if evento[campo] is not None else None
            eventos.append(evento)
        return eventos
