"""Caixa de treino: um banco só na memória, para a pessoa aprender a vender sem medo de errar.

Nada do que acontece no treino chega ao banco da loja: não entra no caixa, não baixa estoque, não imprime, não emite
nota nem gera Pix. O banco de treino nasce com as sementes do sistema, três produtos de exemplo com códigos fáceis
(1, 2 e 3), o turno já aberto e o mesmo jeito de vender da loja (com ou sem mesas e comandas).
"""
from __future__ import annotations

from src.controllers.acesso_controller import AcessoController, Operador
from src.controllers.cadastro_controller import CadastroController
from src.controllers.turno_controller import TurnoController
from src.database.conexao import BancoDados

NOME_OPERADOR = "TREINO"
FUNDO_CENT = 10000
# (código, nome, preço em centavos): os tutoriais citam estes códigos.
PRODUTOS = (("1", "AGUA (TREINO)", 300), ("2", "REFRIGERANTE (TREINO)", 600), ("3", "CERVEJA (TREINO)", 800))
# O que faz o caixa de treino parecer com o da loja. O resto fica no padrão do sistema.
COPIAR = ("usar_mesas", "usar_garotas", "edicao")
# Desligado no treino, custe o que custar: nada sai para impressora, SEFAZ ou Mercado Pago.
SEGURAS = {"imprimir_cupom": "N", "imprimir_saida_ao_pagar": "N", "pix_integrado": "N", "nfce_emissao": "desligada", "pix_mp_token": "",
           "nfce_token_homologacao": "", "nfce_token_producao": ""}


def criar_banco(banco_loja=None) -> tuple[BancoDados, Operador]:
    """Devolve o banco de treino (na memória) e o operador de treino, com o turno aberto."""
    banco = BancoDados(":memory:")
    if banco_loja is not None:
        for chave in COPIAR:
            valor = banco_loja.cfg(chave)
            if valor is not None:
                banco.cfg_set(chave, valor)
        nome = banco_loja.valor("SELECT COALESCE(NULLIF(nome_fantasia, ''), razao_social) FROM loja WHERE id = 1")
        if nome:
            banco.executar("UPDATE loja SET nome_fantasia = ? WHERE id = 1", (f"{nome} (TREINO)",))
    for chave, valor in SEGURAS.items():
        banco.cfg_set(chave, valor)
    cadastros = CadastroController(banco)
    operador_id = cadastros.salvar("operadores", {"nome": NOME_OPERADOR, "senha": "treino", "nivel": 4})
    subgrupo = banco.valor("SELECT id FROM subgrupos ORDER BY id LIMIT 1")
    unidade = banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'") or banco.valor("SELECT id FROM unidades LIMIT 1")
    for codigo, nome, preco in PRODUTOS:
        cadastros.salvar("produtos", {"codigo": codigo, "nome": nome, "subgrupo_id": subgrupo, "unidade_id": unidade,
                                      "preco_cent": f"{preco // 100},{preco % 100:02d}", "controla_estoque": "N"})
    TurnoController(banco).abrir(operador_id, 1, FUNDO_CENT)
    return banco, AcessoController(banco).operador(operador_id)
