"""Importação de produtos em massa por planilha: leitura (CSV e Excel), prévia, regras de código e gravação em bloco."""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src.controllers.importacao_produtos import ImportacaoProdutos, ler_tabela
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


def csv_temp(testcase, texto: str, nome="produtos.csv", codificacao="utf-8-sig") -> str:
    pasta = tempfile.mkdtemp()
    testcase.addCleanup(__import__("shutil").rmtree, pasta, True)
    caminho = Path(pasta) / nome
    caminho.write_bytes(texto.encode(codificacao))
    return str(caminho)


def xlsx_bytes(linhas: list[list]) -> bytes:
    """Um .xlsx mínimo (primeira planilha com textos compartilhados e números), como o Excel grava."""
    textos: list[str] = []

    def idx(t):
        if t not in textos:
            textos.append(t)
        return textos.index(t)
    linhas_xml = []
    for i, linha in enumerate(linhas, start=1):
        celulas = []
        for j, v in enumerate(linha):
            ref = f"{chr(65 + j)}{i}"
            if isinstance(v, (int, float)):
                celulas.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif v != "":
                celulas.append(f'<c r="{ref}" t="s"><v>{idx(v)}</v></c>')
        linhas_xml.append(f'<row r="{i}">{"".join(celulas)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(linhas_xml)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>{"".join(f"<si><t>{t}</t></si>" for t in textos)}</sst>')
    return saida.getvalue()


class TesteLeitura(BaseTeste):
    def test_csv_com_ponto_e_virgula_e_titulos_do_jeito_que_a_boate_escreve(self):
        caminho = csv_temp(self, "Bebida;Valor;Comissao\r\nÁGUA;R$ 10,00;\r\nCAMPARI;R$ 45,00;R$ 15,00\r\n")
        t = ler_tabela(caminho)
        self.assertEqual([(l["nome"], l["preco"], l.get("comissao", "")) for l in t], [("ÁGUA", "R$ 10,00", ""), ("CAMPARI", "R$ 45,00", "R$ 15,00")])
        self.assertEqual([l["_linha"] for l in t], [2, 3])

    def test_csv_com_virgula_e_acentos_do_windows(self):
        caminho = csv_temp(self, "Código,Produto,Preço\n7,GUARANÁ,8.50\n", codificacao="cp1252")
        (l,) = ler_tabela(caminho)
        self.assertEqual((l["codigo"], l["nome"], l["preco"]), ("7", "GUARANÁ", "8.50"))

    def test_excel_xlsx(self):
        caminho = csv_temp(self, "", "p.xlsx")
        Path(caminho).write_bytes(xlsx_bytes([["Código", "Produto", "Preço", "Quantidade"], [1, "SKOL", 8.5, 24], [2, "AGUA", "3,50", ""]]))
        t = ler_tabela(caminho)
        self.assertEqual([(l["codigo"], l["nome"], l["preco"], l.get("quantidade", "")) for l in t], [("1", "SKOL", "8.5", "24"), ("2", "AGUA", "3,50", "")])

    def test_comissao_com_percentual_no_titulo_e_percentual(self):
        t = ler_tabela(csv_temp(self, "Produto;Preço;Comissão %\nX;10,00;20\n"))
        self.assertEqual(t[0]["comissao_pct"], "20")
        self.assertNotIn("comissao", t[0])

    def test_arquivos_que_nao_servem(self):
        with self.assertRaisesRegex(ErroNegocio, "vazia"):
            ler_tabela(csv_temp(self, ""))
        with self.assertRaisesRegex(ErroNegocio, "coluna do nome"):
            ler_tabela(csv_temp(self, "Preço;Qtd\n1;2\n"))
        with self.assertRaisesRegex(ErroNegocio, "Não consegui ler"):
            ler_tabela("/caminho/que/nao/existe.csv")
        ruim = csv_temp(self, "", "ruim.xlsx")
        Path(ruim).write_bytes(b"isto nao e um excel")
        with self.assertRaisesRegex(ErroNegocio, "abrir esse arquivo Excel"):
            ler_tabela(ruim)


class TestePrevia(BaseTeste):
    def setUp(self):
        super().setUp()
        self.imp = ImportacaoProdutos(self.banco)

    def previa(self, linhas: list[dict], **kw):
        tabela = [{"_linha": i + 2, **l} for i, l in enumerate(linhas)]
        return self.imp.analisar(tabela, **kw)

    def test_sem_codigo_numera_em_sequencia_e_pula_o_codigo_da_comissao(self):
        p = self.previa([{"nome": f"P{i}", "preco": "1,00"} for i in range(5)], sequencia_a_partir_de=48, usar_codigo_da_planilha=False)
        self.assertEqual([int(l.codigo) for l in p.linhas], [48, 49, 51, 52, 53])          # o 50 é da comissão das garotas

    def test_a_sequencia_comeca_depois_do_maior_codigo_que_ja_existe(self):
        self.novo_produto("EXISTENTE", 500, codigo="12")
        p = self.previa([{"nome": "NOVO", "preco": "2,00"}])
        self.assertEqual(int(p.linhas[0].codigo), 13)

    def test_codigo_reservado_do_caixa_na_planilha_e_recusado(self):
        p = self.previa([{"codigo": "50", "nome": "ALGO", "preco": "5,00"}, {"codigo": "1002", "nome": "OUTRO", "preco": "5,00"}])
        self.assertEqual([l.acao for l in p.linhas], ["recusar", "recusar"])
        self.assertIn("reservado", p.linhas[0].motivo)

    def test_codigo_da_planilha_respeitado_e_sequencia_nao_colide_com_ele(self):
        p = self.previa([{"codigo": "2", "nome": "A", "preco": "1"}, {"nome": "B", "preco": "1"}, {"nome": "C", "preco": "1"}], sequencia_a_partir_de=1)
        self.assertEqual([int(l.codigo) for l in p.linhas], [2, 1, 3])

    def test_renumerar_tudo_ignora_a_coluna_codigo(self):
        p = self.previa([{"codigo": "99", "nome": "A", "preco": "1"}, {"codigo": "77", "nome": "B", "preco": "1"}], sequencia_a_partir_de=1,
                        usar_codigo_da_planilha=False)
        self.assertEqual([int(l.codigo) for l in p.linhas], [1, 2])

    def test_existente_pelo_codigo_ou_pelo_nome_vira_atualizacao(self):
        pid = self.novo_produto("SKOL", 800, codigo="1")
        p = self.previa([{"codigo": "1", "nome": "SKOL", "preco": "9,00"}, {"nome": "skol", "preco": "9,50"}])
        self.assertEqual([l.acao for l in p.linhas], ["atualizar", "recusar"])               # a 2ª repete o produto da 1ª
        self.assertEqual(p.linhas[0].produto_id, pid)
        p2 = self.previa([{"nome": "skol", "preco": "9,50"}])
        self.assertEqual((p2.linhas[0].acao, int(p2.linhas[0].codigo)), ("atualizar", 1))

    def test_desligar_atualizar_recusa_os_existentes(self):
        self.novo_produto("SKOL", 800, codigo="1")
        p = self.previa([{"codigo": "1", "nome": "SKOL", "preco": "9,00"}], atualizar_existentes=False)
        self.assertEqual(p.linhas[0].acao, "recusar")

    def test_conflitos_de_codigo_e_nome(self):
        self.novo_produto("SKOL", 800, codigo="1")
        self.novo_produto("BRAHMA", 800, codigo="2")
        p = self.previa([{"codigo": "1", "nome": "BRAHMA", "preco": "1"},       # o código é da SKOL e o nome é da BRAHMA
                         {"codigo": "5", "nome": "SKOL", "preco": "1"}])        # nome de outro código
        self.assertIn("já é de 'SKOL'", p.linhas[0].motivo)
        self.assertIn("Já existe 'SKOL' com o código 1", p.linhas[1].motivo)

    def test_mesmo_codigo_com_nome_novo_e_renomeacao_avisada(self):
        self.novo_produto("SKOL", 800, codigo="1")
        (l,) = self.previa([{"codigo": "1", "nome": "SKOL LATA", "preco": "9"}]).linhas
        self.assertEqual(l.acao, "atualizar")
        self.assertIn("O nome vai mudar de 'SKOL' para 'SKOL LATA'", l.avisos[0])

    def test_repeticoes_dentro_da_propria_planilha(self):
        p = self.previa([{"codigo": "3", "nome": "A", "preco": "1"}, {"codigo": "3", "nome": "B", "preco": "1"}, {"codigo": "4", "nome": "a", "preco": "1"}])
        self.assertEqual([l.acao for l in p.linhas], ["criar", "recusar", "recusar"])
        self.assertIn("linha 2", p.linhas[1].motivo)
        self.assertIn("linha 2", p.linhas[2].motivo)

    def test_erros_de_preenchimento_viram_motivo_e_nao_derrubam_a_importacao(self):
        p = self.previa([{"nome": "", "preco": "1"}, {"nome": "SEM PRECO"}, {"nome": "PRECO RUIM", "preco": "abc"}, {"nome": "N" * 51, "preco": "1"},
                         {"nome": "UNIDADE", "preco": "1", "unidade": "XX"}, {"nome": "NEGATIVO", "preco": "-5"},
                         {"nome": "QTD RUIM", "preco": "1", "quantidade": "muitas"}, {"nome": "BOA", "preco": "1"}])
        self.assertEqual([l.acao for l in p.linhas], ["recusar"] * 7 + ["criar"])
        motivos = " | ".join(l.motivo for l in p.linhas)
        for esperado in ("Falta o nome", "Falta o preço", "Preço inválido", "passa de 50", "unidade 'XX'", "não pode ser negativo", "Quantidade inválido"):
            self.assertIn(esperado, motivos)

    def test_comissao_em_reais_vira_percentual_certo(self):
        p = self.previa([{"nome": "CAMPARI", "preco": "45,00", "comissao": "R$ 15,00"}, {"nome": "VODKA", "preco": "40,00", "comissao": "10,00"},
                         {"nome": "ERRO", "preco": "10,00", "comissao": "15,00"}, {"nome": "PCT", "preco": "10,00", "comissao_pct": "20"}])
        self.assertEqual([l.comissao_pct for l in p.linhas], [33.3333, 25.0, None, 20.0])
        self.assertIn("maior que o preço", p.linhas[2].motivo)

    def test_grupo_novo_gera_aviso_e_grupo_existente_nao(self):
        p = self.previa([{"nome": "A", "preco": "1", "grupo": "Cervejas"}, {"nome": "B", "preco": "1"}])
        self.assertIn("será criado", p.linhas[0].avisos[0])
        self.assertEqual(p.linhas[1].avisos, [])                                  # DIVERSOS já existe
        self.assertEqual(p.linhas[0].grupo, "CERVEJAS")

    def test_nomes_em_maiusculas_por_padrao_e_opcional(self):
        self.assertEqual(self.previa([{"nome": "  coca   cola ", "preco": "1"}]).linhas[0].nome, "COCA COLA")
        self.assertEqual(self.previa([{"nome": "Coca Cola", "preco": "1"}], maiusculas=False).linhas[0].nome, "Coca Cola")

    def test_codigo_de_barras_repetido_e_recusado(self):
        self.novo_produto("SKOL", 800, codigo="1", cbarra="7891234567895")
        p = self.previa([{"codigo": "2", "nome": "OUTRA", "preco": "1", "codigo_barras": "7891234567895"}])
        self.assertIn("código de barras", p.linhas[0].motivo)


class TesteGravacao(BaseTeste):
    def setUp(self):
        super().setUp()
        self.imp = ImportacaoProdutos(self.banco)

    def importar(self, linhas, **kw):
        previa = self.imp.analisar([{"_linha": i + 2, **l} for i, l in enumerate(linhas)], **kw)
        return self.imp.importar(previa)

    def produto(self, nome):
        return dict(self.banco.um("SELECT * FROM produtos WHERE nome = ?", (nome,)))

    def test_cria_produtos_com_grupo_unidade_comissao_e_codigo(self):
        r = self.importar([{"codigo": "1", "nome": "CAMPARI", "preco": "45,00", "comissao": "15,00", "grupo": "Doses", "unidade": "un"},
                           {"nome": "ÁGUA", "preco": "10"}])
        self.assertEqual(r, {"criados": 2, "atualizados": 0, "estoque": 0})
        p = self.produto("CAMPARI")
        self.assertEqual((p["codigo"], p["preco_cent"], p["comissao_pct"], p["controla_estoque"], p["ativo"], p["venda"]),
                         ("0000000000001", 4500, 33.3333, 0, 1, 1))
        self.assertEqual(self.banco.valor("SELECT g.nome FROM subgrupos s JOIN grupos g ON g.id = s.grupo_id WHERE s.id = ?", (p["subgrupo_id"],)), "DOSES")
        self.assertEqual(int(self.produto("ÁGUA")["codigo"]), 2)
        self.assertEqual(fmt.pct_de(4500, p["comissao_pct"]), 1500)               # a comissão no caixa dá os R$ 15,00 da lista

    def test_grupos_repetidos_na_planilha_criam_um_so(self):
        self.importar([{"nome": "A", "preco": "1", "grupo": "Cervejas"}, {"nome": "B", "preco": "1", "grupo": "CERVEJAS"}])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM grupos WHERE nome = 'CERVEJAS'"), 1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM subgrupos WHERE nome = 'CERVEJAS'"), 1)

    def test_atualiza_preco_sem_mexer_no_resto(self):
        pid = self.novo_produto("SKOL", 800, codigo="1", estoque=True, qt=50)
        self.banco.executar("UPDATE produtos SET estoque_minimo = 10 WHERE id = ?", (pid,))
        r = self.importar([{"codigo": "1", "nome": "SKOL", "preco": "9,00"}])
        self.assertEqual((r["criados"], r["atualizados"]), (0, 1))
        p = self.produto("SKOL")
        self.assertEqual((p["id"], p["preco_cent"], p["qt_atual"], p["estoque_minimo"], p["controla_estoque"]), (pid, 900, 50, 10, 1))

    def test_estoque_inicial_pela_planilha_vira_lancamento_e_historico(self):
        r = self.importar([{"nome": "SKOL", "preco": "8", "quantidade": "48", "estoque_minimo": "12"},
                           {"nome": "SO MINIMO", "preco": "8", "estoque_minimo": "5"},
                           {"nome": "CONTROLA", "preco": "8", "controla_estoque": "S"},
                           {"nome": "SEM CONTROLE", "preco": "8"}])
        self.assertEqual(r["estoque"], 3)
        skol = self.produto("SKOL")
        self.assertEqual((skol["controla_estoque"], skol["qt_atual"], skol["estoque_minimo"], skol["qt_inicial"]), (1, 48, 12, 48))
        self.assertEqual(self.produto("SO MINIMO")["estoque_minimo"], 5)
        self.assertEqual((self.produto("CONTROLA")["controla_estoque"], self.produto("CONTROLA")["qt_atual"]), (1, 0))
        self.assertEqual(self.produto("SEM CONTROLE")["controla_estoque"], 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque WHERE tipo = 'inicial'"), 1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE produto_id = ?", (skol["id"],)), 1)

    def test_tudo_ou_nada_se_algo_falha_no_meio_nada_e_gravado(self):
        antes = self.banco.valor("SELECT COUNT(*) FROM produtos")
        with mock.patch.object(self.imp.estoque, "adicionar_item", side_effect=ErroNegocio("falhou")), self.assertRaises(ErroNegocio):
            self.importar([{"nome": "A", "preco": "1", "grupo": "NOVO"}, {"nome": "B", "preco": "1", "quantidade": "3"}])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), antes)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM grupos WHERE nome = 'NOVO'"), 0)

    def test_so_recusados_nao_importa(self):
        with self.assertRaisesRegex(ErroNegocio, "Nada para importar"):
            self.importar([{"nome": "", "preco": "1"}])

    def test_recusados_ficam_de_fora_e_os_bons_entram(self):
        r = self.importar([{"nome": "BOM", "preco": "1"}, {"nome": "RUIM", "preco": "xx"}])
        self.assertEqual(r["criados"], 1)
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE nome = 'RUIM'"))

    def test_o_produto_importado_vende_no_caixa(self):
        from src.controllers.caixa_controller import CaixaController
        from src.controllers.turno_controller import TurnoController
        self.importar([{"codigo": "7", "nome": "CERVEJA", "preco": "15,00"}])
        TurnoController(self.banco).abrir(self.operador_adm(), 1, 10000)
        caixa = CaixaController(self.banco, self.operador_adm())
        venda = caixa.abrir_balcao()
        caixa.adicionar_item(venda, self.produto("CERVEJA")["id"], 2)
        self.assertEqual(caixa.recalcular(venda)["subtotal"], 3000)

    def test_exportar_e_importar_de_volta_nao_muda_nada(self):
        self.importar([{"codigo": "1", "nome": "CAMPARI", "preco": "45,00", "comissao": "15,00", "grupo": "DOSES", "quantidade": "6", "estoque_minimo": "2"},
                       {"codigo": "2", "nome": "ÁGUA", "preco": "10,00"}])
        antes = [dict(r) for r in self.banco.todos("SELECT * FROM produtos ORDER BY id")]
        pasta = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, pasta, True)
        arquivo = Path(pasta) / "exportado.csv"
        arquivo.write_text(self.imp.exportar(), encoding="utf-8-sig", newline="")
        previa = self.imp.analisar(ler_tabela(str(arquivo)))
        self.assertEqual([l.acao for l in previa.linhas][:2], ["atualizar", "atualizar"])
        self.imp.importar(previa)
        depois = [dict(r) for r in self.banco.todos("SELECT * FROM produtos ORDER BY id")]
        for a, d in zip(antes, depois):
            for campo in ("codigo", "nome", "preco_cent", "comissao_pct", "subgrupo_id", "unidade_id", "qt_atual", "estoque_minimo", "controla_estoque"):
                self.assertEqual(a[campo], d[campo], campo)

    def test_modelo_pode_ser_lido_de_volta(self):
        caminho = csv_temp(self, self.imp.modelo())
        previa = self.imp.analisar(ler_tabela(caminho))
        self.assertEqual(previa.contar("recusar"), 0)
        self.assertEqual(previa.contar("criar"), 2)


if __name__ == "__main__":
    unittest.main()
