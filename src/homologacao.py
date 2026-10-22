"""Roteiro automático em banco descartável, sem rede, licença de loja ou periféricos."""
from __future__ import annotations

import json
from contextlib import ExitStack, closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from src.controllers.cadastro_controller import CadastroController
from src.controllers.caixa_controller import CaixaController
from src.controllers.fila_impressao_controller import FilaImpressao
from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados


class _InterrupcaoSimulada(BaseException):
    pass


def _verificar(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise RuntimeError(mensagem)


def executar(arquivo: str | None = None) -> int:
    """Nunca abre PDV_DB. Apenas o relatório solicitado sai da pasta temporária."""
    resultado = {"inicio": fmt.agora(), "isolado": True, "cenarios": [], "ok": False,
                 "limites": "Não homologa queda elétrica real, disco, rede, banco/cartão ou hardware físico."}
    banco = None
    try:
        with TemporaryDirectory(prefix="willpdv-homologacao-") as pasta, ExitStack() as limpeza:
            limpeza.callback(lambda: banco.fechar() if banco is not None else None)
            caminho = str(Path(pasta) / "teste.db")
            banco = BancoDados(caminho)
            adm = banco.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
            dinheiro = banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")
            cadastro = CadastroController(banco)
            produto = cadastro.salvar("produtos", {
                "codigo": cadastro.proximo_codigo_produto(), "nome": "PRODUTO DE HOMOLOGACAO",
                "subgrupo_id": banco.valor("SELECT id FROM subgrupos LIMIT 1"),
                "unidade_id": banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'"),
                "preco_cent": "10,00", "controla_estoque": "S",
            })
            banco.executar("UPDATE produtos SET qt_atual = 10 WHERE id = ?", (produto,))
            TurnoController(banco).abrir(adm, 1, 0)
            caixa = CaixaController(banco, adm)
            venda = caixa.abrir_balcao()
            caixa.adicionar_item(venda, produto, 2)
            caixa.adicionar_pagamento(venda, dinheiro, 1000)
            uuid = banco.valor("SELECT uuid FROM vendas WHERE id = ?", (venda,))
            banco.fechar()
            banco = BancoDados(caminho, semear=False)
            caixa = CaixaController(banco, adm)
            _verificar(caixa.balcao_aberto()["id"] == venda, "Balcão não retomado.")
            _verificar(banco.valor("SELECT uuid FROM vendas WHERE id = ?", (venda,)) == uuid, "UUID alterado.")
            _verificar(banco.valor("SELECT COUNT(*) FROM pagamentos_venda WHERE venda_id = ?", (venda,)) == 1,
                       "Pagamento parcial perdido ou duplicado.")
            resultado["cenarios"].append("Retomada: mesma venda e pagamento parcial persistidos.")
            try:
                with banco.transacao():
                    caixa.adicionar_pagamento(venda, dinheiro, 1000)
                    caixa.fechar(venda)
                    raise _InterrupcaoSimulada()
            except _InterrupcaoSimulada:
                pass
            banco.fechar()
            banco = BancoDados(caminho, semear=False)
            caixa = CaixaController(banco, adm)
            _verificar(banco.valor("SELECT status FROM vendas WHERE id = ?", (venda,)) == "aberta",
                       "Fechamento incompleto foi confirmado.")
            _verificar(banco.valor("SELECT COUNT(*) FROM pagamentos_venda WHERE venda_id = ?", (venda,)) == 1,
                       "Pagamento incompleto não foi revertido.")
            resultado["cenarios"].append("Atomicidade: pagamento e fechamento interrompidos foram revertidos juntos.")
            caixa.adicionar_pagamento(venda, dinheiro, 1000)
            caixa.fechar(venda)
            cupom = banco.valor("SELECT cupom FROM vendas WHERE id = ?", (venda,))
            estoque = banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto,))
            try:
                caixa.fechar(venda)
            except ErroNegocio:
                pass
            _verificar(banco.valor("SELECT cupom FROM vendas WHERE id = ?", (venda,)) == cupom and cupom is not None,
                       "Cupom alterado ao repetir fechamento.")
            _verificar(banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto,)) == estoque == 8,
                       "Estoque não corresponde a uma venda única.")
            _verificar(banco.valor("SELECT COUNT(*) FROM pagamentos_venda WHERE venda_id = ?", (venda,)) == 2,
                       "Pagamentos não correspondem a dois recebimentos únicos.")
            resultado["cenarios"].append("Fechamento repetido: cupom, estoque e pagamentos sem duplicação.")

            def interromper(item, maquina):
                raise _InterrupcaoSimulada()

            fila = FilaImpressao(banco, interromper)
            documento = fila.enfileirar("caixa", "cupom_teste", b"TESTE SEM HARDWARE", venda_id=venda)
            try:
                fila.processar()
            except _InterrupcaoSimulada:
                pass
            banco.fechar()
            banco = BancoDados(caminho, semear=False)
            enviados = []
            fila = FilaImpressao(banco, lambda item, maquina: enviados.append(item["id"]))
            _verificar(fila.recuperar_interrompidos() == 1, "Envio interrompido não detectado.")
            fila.reenviar_todos()
            fila.processar()
            _verificar(not enviados, "Envio incerto foi repetido automaticamente.")
            fila.conferir_interrompido(documento, impresso=True, operador_id=adm)
            fila.processar()
            _verificar(not enviados, "Papel confirmado foi reenviado.")
            resultado["cenarios"].append("Impressão interrompida: conferência obrigatória, sem reenvio automático.")
            copia = str(Path(pasta) / "restauracao.db")
            with closing(sqlite3.connect(copia)) as restaurado:
                banco.conexao.backup(restaurado)
                _verificar(restaurado.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                           "Integridade da cópia inválida.")
                _verificar(restaurado.execute("SELECT uuid, cupom FROM vendas").fetchall() == [(uuid, cupom)],
                           "Venda divergente na restauração.")
            resultado["cenarios"].append("Cópia SQLite restaurada isoladamente com integridade e cupom conferidos.")
            banco.fechar()
            banco = None
            resultado["ok"] = True
    except Exception as erro:
        resultado["erro"] = f"{type(erro).__name__}: {erro}"
    finally:
        if banco is not None:
            banco.fechar()
    resultado["fim"] = fmt.agora()
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if arquivo:
        destino = Path(arquivo)
        if destino.suffix.lower() != ".json":
            raise ValueError("O relatório deve ter extensão .json; nenhum banco de loja pode ser usado como destino.")
        with destino.open("x", encoding="utf-8") as saida:
            saida.write(texto + "\n")
    print(texto)
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("relatorio", nargs="?", help="Arquivo JSON opcional com o resultado.")
    argumentos = parser.parse_args()
    raise SystemExit(executar(argumentos.relatorio))
