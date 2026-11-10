"""Vários caixas na mesma loja: o caixa adicional usa o banco do principal pela rede (src/database/rede.py)."""
import os
import sqlite3
import tempfile
import threading
import unittest

from src.core.erros import ErroNegocio
from src.database import rede
from src.database.conexao import BancoDados


class BaseRede(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.caminho = os.path.join(self.pasta.name, "loja.db")
        self.principal = BancoDados(self.caminho)
        self.addCleanup(self.principal.fechar)
        self.chave = rede.nova_chave()
        self.servidor = rede.ServidorBanco(self.caminho, self.chave, porta=0, host="127.0.0.1")
        self.servidor.iniciar()
        self.addCleanup(self.servidor.parar)
        self.url = rede.url("127.0.0.1", self.servidor.porta)

    def adicional(self, terminal=2, instalacao=None, chave=None):
        rede.registrar_ligacao(self.url, chave or self.chave, terminal, instalacao or f"pc-{terminal}")
        self.addCleanup(rede.esquecer_ligacao, self.url)
        banco = BancoDados(self.url, semear=False)
        self.addCleanup(banco.fechar)
        return banco


class TesteBancoRemoto(BaseRede):
    def test_abre_o_banco_do_principal_com_a_mesma_interface(self):
        banco = self.adicional()
        self.assertIsInstance(banco, rede.BancoRemoto)
        self.assertTrue(banco.remoto)
        self.assertFalse(self.principal.remoto)
        self.principal.cfg_set("nome_teste", "Adega do Zé")
        self.assertEqual(banco.cfg("nome_teste"), "Adega do Zé")
        linha = banco.um("SELECT chave, valor FROM config WHERE chave = ?", ("nome_teste",))
        self.assertEqual((linha["chave"], linha[1], linha["VALOR"]), ("nome_teste", "Adega do Zé", "Adega do Zé"))
        self.assertEqual(dict(linha), {"chave": "nome_teste", "valor": "Adega do Zé"})
        self.assertEqual(linha.keys(), ["chave", "valor"])
        self.assertEqual(banco.valor("SELECT norm(?)", ("Café",)), "CAFE")
        self.assertIsNone(banco.um("SELECT 1 WHERE 0"))
        self.assertEqual([r[0] for r in banco.executar("SELECT 1 UNION SELECT 2")], [1, 2])

    def test_terminal_e_do_computador_e_nao_da_loja(self):
        banco = self.adicional(terminal=3)
        self.assertEqual(banco.cfg_int("terminal", 1), 3)
        banco.cfg_set("terminal", 9)
        self.assertEqual(banco.cfg_int("terminal", 1), 3)
        self.assertEqual(self.principal.cfg_int("terminal", 1), 1)

    def test_inserir_devolve_id_e_bytes_ida_e_volta(self):
        banco = self.adicional()
        foto = bytes(range(256)) * 40
        item = banco.inserir("fila_impressao", {"criado_em": "2026-11-10 10:00:00", "destino": "caixa",
                                                "nome": "cupom", "dados": foto, "status": "pendente"})
        self.assertEqual(self.principal.valor("SELECT dados FROM fila_impressao WHERE id = ?", (item,)), foto)
        self.assertEqual(banco.valor("SELECT dados FROM fila_impressao WHERE id = ?", (item,)), foto)
        mudou = banco.executar("UPDATE fila_impressao SET status = 'enviado' WHERE id = ?", (item,)).rowcount
        self.assertEqual(mudou, 1)

    def test_transacao_desfaz_tudo_e_savepoint_desfaz_so_o_trecho(self):
        banco = self.adicional()
        with self.assertRaises(RuntimeError):
            with banco.transacao():
                banco.cfg_set("a", "1")
                self.assertTrue(banco.conexao.in_transaction)
                raise RuntimeError("falhou")
        self.assertFalse(banco.conexao.in_transaction)
        self.assertEqual(self.principal.cfg("a", "-"), "-")
        with banco.transacao():
            banco.cfg_set("b", "1")
            with self.assertRaises(RuntimeError):
                with banco.transacao():
                    banco.cfg_set("c", "1")
                    raise RuntimeError("só o trecho")
        self.assertEqual((self.principal.cfg("b", "-"), self.principal.cfg("c", "-")), ("1", "-"))

    def test_erro_do_sqlite_chega_com_o_mesmo_tipo_e_texto(self):
        banco = self.adicional()
        banco.executar("INSERT INTO config(chave, valor) VALUES ('unica', '1')")
        with self.assertRaises(sqlite3.IntegrityError) as erro:
            banco.executar("INSERT INTO config(chave, valor) VALUES ('unica', '2')")
        self.assertIn("config.chave", str(erro.exception))
        with self.assertRaises(sqlite3.OperationalError):
            banco.executar("SELECT * FROM tabela_que_nao_existe")
        self.assertEqual(banco.cfg("unica"), "1")           # a ligação continua boa depois do erro

    def test_nao_anexa_outro_arquivo_do_principal(self):
        banco = self.adicional()
        with self.assertRaises(sqlite3.DatabaseError):
            banco.executar("ATTACH DATABASE ? AS outro", (os.path.join(self.pasta.name, "outro.db"),))

    def test_backup_fica_no_principal(self):
        with self.assertRaises(ErroNegocio):
            self.adicional().copiar_para(os.path.join(self.pasta.name, "copia.db"))

    def test_backup_automatico_no_adicional_nao_e_falha(self):
        from src.controllers.utilitario_controller import UtilitarioController
        banco = self.adicional()
        self.assertIsNotNone(UtilitarioController(banco).backup_automatico("troca de turno"))
        self.assertEqual(self.principal.cfg("backup_erro"), "")

    def test_texto_com_acento_e_emoji_vai_e_volta(self):
        banco = self.adicional()
        texto = "Açaí 500 ml 🍺 — promoção"
        banco.cfg_set("texto", texto)
        self.assertEqual((banco.cfg("texto"), self.principal.cfg("texto")), (texto, texto))

    def test_auditoria_registra_o_operador_do_caixa_adicional(self):
        banco = self.adicional()
        operador = self.principal.valor("SELECT id FROM operadores WHERE ativo = 1 ORDER BY id LIMIT 1")
        banco.definir_operador_auditoria(operador)
        banco.registrar_auditoria("teste", "1", "criar", depois={"x": 1})
        self.assertEqual(self.principal.valor(
            "SELECT operador_id FROM auditoria_eventos WHERE entidade = 'teste'"), operador)
        with self.assertRaises(ValueError):
            banco.definir_operador_auditoria(987654)


class TesteEntrada(BaseRede):
    def test_codigo_errado_nao_entra(self):
        with self.assertRaises(rede.ErroLigacao) as erro:
            self.adicional(chave=rede.nova_chave())
        self.assertIn("código de ligação", str(erro.exception))

    def test_principal_desligado_avisa_em_portugues(self):
        self.servidor.parar()
        with self.assertRaises(rede.ErroLigacao) as erro:
            self.adicional()
        self.assertIn("Sem ligação com o caixa principal", str(erro.exception))

    def test_numero_do_principal_e_recusado(self):
        self.principal.cfg_set("terminal", "2")
        with self.assertRaises(rede.ErroLigacao) as erro:
            self.adicional(terminal=2)
        self.assertIn("caixa principal", str(erro.exception))

    def test_dois_computadores_nao_dividem_o_mesmo_numero(self):
        self.adicional(terminal=2, instalacao="pc-a")
        with self.assertRaises(rede.ErroLigacao) as erro:
            self.adicional(terminal=2, instalacao="pc-b")
        self.assertIn("já é de outro computador", str(erro.exception))
        self.adicional(terminal=2, instalacao="pc-a")            # o mesmo computador abre outra ligação
        self.assertTrue(rede.liberar_terminal(self.principal, 2))
        self.adicional(terminal=2, instalacao="pc-b")            # liberado: a máquina nova assume o número

    def test_versao_diferente_e_recusada(self):
        from unittest import mock
        real = rede._Canal.enviar

        def anunciar_outra_versao(canal, mensagem):
            if mensagem.get("o") == "ola":
                mensagem = {**mensagem, "versao": "0.0.1"}
            return real(canal, mensagem)

        with mock.patch.object(rede._Canal, "enviar", anunciar_outra_versao):
            with self.assertRaises(rede.ErroLigacao) as erro:
                self.adicional()
        self.assertIn("mesma versão", str(erro.exception))

    def test_lista_os_caixas_ligados(self):
        self.adicional(terminal=2)
        self.adicional(terminal=2)
        self.adicional(terminal=5)
        ligados = self.servidor.conectados()
        self.assertEqual([(c["terminal"], c["ligacoes"]) for c in ligados], [(2, 2), (5, 1)])


class TesteQueda(BaseRede):
    def test_queda_no_meio_da_transacao_desfaz_e_nao_grava_o_resto(self):
        banco = self.adicional()
        with self.assertRaises(rede.ErroLigacao):
            with banco.transacao():
                banco.cfg_set("antes", "1")
                self.servidor.parar()
                try:
                    banco.cfg_set("depois", "1")
                except rede.ErroLigacao:
                    pass
                self.servidor = rede.ServidorBanco(self.caminho, self.chave, porta=int(self.url.rsplit(":", 1)[1]),
                                                   host="127.0.0.1")
                self.servidor.iniciar()
                self.addCleanup(self.servidor.parar)
                banco.cfg_set("fora_da_transacao", "1")      # não pode religar e gravar solto
        self.assertFalse(banco.conexao.in_transaction)
        for chave in ("antes", "depois", "fora_da_transacao"):
            self.assertEqual(self.principal.cfg(chave, "-"), "-", chave)
        banco.cfg_set("voltou", "1")                          # religa sozinho no próximo comando
        self.assertEqual(self.principal.cfg("voltou"), "1")

    def test_adicional_que_some_solta_a_trava_de_escrita(self):
        banco = self.adicional()
        banco.executar("BEGIN IMMEDIATE")
        banco.cfg_set("pela_metade", "1")
        banco.conexao._canal.sock.close()                     # cabo puxado, sem despedida
        for _ in range(200):
            if not self.servidor.conectados():
                break
            threading.Event().wait(0.02)
        self.principal.cfg_set("principal_escreve", "1")      # não fica esperando a trava
        self.assertEqual(self.principal.cfg("pela_metade", "-"), "-")


class TesteDoisCaixasVendendo(BaseRede):
    """As regras de venda rodando nos dois caixas contra o mesmo banco."""

    def setUp(self):
        super().setUp()
        from src.controllers.contexto import Contexto
        self.remoto = self.adicional(terminal=2)
        self.ctx1 = Contexto(self.principal)
        self.ctx2 = Contexto(self.remoto)
        for ctx in (self.ctx1, self.ctx2):
            ctx.operador = ctx.acesso.autenticar("ADM", "ADM")

    def produto(self, nome, preco, qt):
        from src.controllers.cadastro_controller import CadastroController
        cad = CadastroController(self.principal)
        pid = cad.salvar("produtos", {
            "codigo": cad.proximo_codigo_produto(), "nome": nome,
            "subgrupo_id": self.principal.valor("SELECT id FROM subgrupos LIMIT 1"),
            "unidade_id": self.principal.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'"),
            "preco_cent": f"{preco / 100:.2f}".replace(".", ","), "controla_estoque": "S"})
        self.principal.executar("UPDATE produtos SET qt_atual = ? WHERE id = ?", (qt, pid))
        return pid

    def test_os_dois_vendem_o_mesmo_produto_ao_mesmo_tempo(self):
        """Estoque um só, cupons sem repetição e cada venda no turno do caixa que a fechou."""
        from src.controllers.contexto import Contexto
        vendas_por_caixa = 12
        lata = self.produto("CERVEJA LATA", 500, 100)
        dinheiro = self.principal.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")
        turnos = {1: self.ctx1.turnos.abrir(self.ctx1.operador_id, 1, 0),
                  2: self.ctx2.turnos.abrir(self.ctx2.operador_id, 1, 0)}
        erros = []

        def vender(abrir_banco):
            banco = abrir_banco()                      # cada thread com a sua conexão, como cada caixa de verdade
            try:
                ctx = Contexto(banco)
                ctx.operador = ctx.acesso.autenticar("ADM", "ADM")
                for _ in range(vendas_por_caixa):
                    venda = ctx.caixa.abrir_balcao()
                    ctx.caixa.adicionar_item(venda, lata, 2)
                    ctx.caixa.adicionar_pagamento(venda, dinheiro, 1000)
                    ctx.caixa.fechar(venda)
            except Exception as erro:  # noqa: BLE001
                erros.append(repr(erro))
            finally:
                banco.fechar()

        threads = [threading.Thread(target=vender, args=(lambda: BancoDados(self.caminho, semear=False),)),
                   threading.Thread(target=vender, args=(lambda: BancoDados(self.url, semear=False),))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(erros, [])
        b = self.principal
        self.assertEqual(b.valor("SELECT qt_atual FROM produtos WHERE id = ?", (lata,)), 100 - 2 * 2 * vendas_por_caixa)
        cupons = [r[0] for r in b.todos("SELECT cupom FROM vendas WHERE status = 'fechada'")]
        self.assertEqual(len(cupons), 2 * vendas_por_caixa)
        self.assertEqual(len(set(cupons)), len(cupons))
        for terminal, turno in turnos.items():
            self.assertEqual(b.valor(
                "SELECT COUNT(*) FROM vendas WHERE status = 'fechada' AND terminal = ? AND turno_id = ?",
                (terminal, turno)), vendas_por_caixa)
        resumo2 = self.ctx2.turnos.resumo(turnos[2])
        self.assertEqual(self.ctx2.turnos.dinheiro_esperado(turnos[2]), 1000 * vendas_por_caixa)
        self.assertEqual(self.ctx1.turnos.dinheiro_esperado(turnos[1]), 1000 * vendas_por_caixa)
        self.assertTrue(resumo2)

    def test_mesa_aberta_num_caixa_e_fechada_no_outro(self):
        """WillPDV (bar e boate): mesa e comanda são da casa, não do caixa que abriu."""
        lata = self.produto("CERVEJA LATA", 500, 10)
        dinheiro = self.principal.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")
        self.ctx1.turnos.abrir(self.ctx1.operador_id, 1, 0)
        turno2 = self.ctx2.turnos.abrir(self.ctx2.operador_id, 1, 0)
        mesa, _ = self.ctx1.caixa.abrir_mesa(5)
        self.ctx1.caixa.adicionar_item(mesa, lata, 2)
        mesma, _ = self.ctx2.caixa.abrir_mesa(5)
        self.assertEqual(mesma, mesa)
        self.ctx2.caixa.adicionar_item(mesa, lata, 1)
        self.ctx2.caixa.adicionar_pagamento(mesa, dinheiro, 1650)      # R$ 15,00 + 10% de serviço da mesa
        self.ctx2.caixa.fechar(mesa)
        venda = self.principal.um("SELECT status, turno_id FROM vendas WHERE id = ?", (mesa,))
        self.assertEqual((venda["status"], venda["turno_id"]), ("fechada", turno2))
        self.assertEqual(self.principal.valor("SELECT qt_atual FROM produtos WHERE id = ?", (lata,)), 7)
        self.assertEqual(self.ctx2.turnos.dinheiro_esperado(turno2), 1650)

    def test_venda_em_andamento_num_caixa_nao_segura_o_turno_do_outro(self):
        lata = self.produto("CERVEJA LATA", 500, 10)
        t1 = self.ctx1.turnos.abrir(self.ctx1.operador_id, 1, 0)
        self.ctx2.turnos.abrir(self.ctx2.operador_id, 1, 0)
        venda2 = self.ctx2.caixa.abrir_balcao()
        self.ctx2.caixa.adicionar_item(venda2, lata, 1)
        self.ctx1.turnos.fechar(t1, self.ctx1.operador_id, 0)
        with self.assertRaises(ErroNegocio):
            self.ctx2.turnos.fechar(self.ctx2.turnos.atual()["id"], self.ctx2.operador_id, 0)

    def test_cada_caixa_tem_o_seu_turno_e_a_sua_venda_de_balcao(self):
        self.assertEqual((self.ctx1.turnos.terminal, self.ctx2.turnos.terminal), (1, 2))
        t1 = self.ctx1.turnos.abrir(self.ctx1.operador_id, 1, 10000)
        self.assertIsNone(self.ctx2.turnos.atual())
        t2 = self.ctx2.turnos.abrir(self.ctx2.operador_id, 1, 5000)
        self.assertNotEqual(t1, t2)
        v1 = self.ctx1.caixa.abrir_balcao()
        v2 = self.ctx2.caixa.abrir_balcao()
        self.assertNotEqual(v1, v2)
        self.assertEqual(self.ctx1.caixa.abrir_balcao(), v1)        # cada um retoma a sua
        self.assertEqual(self.ctx2.caixa.abrir_balcao(), v2)
        self.assertEqual(self.principal.valor("SELECT terminal FROM vendas WHERE id = ?", (v2,)), 2)

    def test_fila_de_impressao_e_de_cada_caixa(self):
        from src.controllers.fila_impressao_controller import FilaImpressao
        saiu = {1: [], 2: []}
        fila1 = FilaImpressao(self.principal, lambda item, maquina: saiu[1].append(item["nome"]))
        fila2 = FilaImpressao(self.remoto, lambda item, maquina: saiu[2].append(item["nome"]))
        fila1.enfileirar("caixa", "cupom do caixa 1", b"um")
        fila2.enfileirar("caixa", "cupom do caixa 2", b"dois")
        self.assertEqual(fila2.contagem()["pendentes"], 1)
        self.assertEqual(fila1.processar()["enviados"], 1)
        self.assertEqual(saiu, {1: ["cupom do caixa 1"], 2: []})
        self.assertEqual(fila2.processar()["enviados"], 1)
        self.assertEqual(saiu, {1: ["cupom do caixa 1"], 2: ["cupom do caixa 2"]})
        self.assertEqual([i["nome"] for i in fila2.listar()], ["cupom do caixa 2"])


class TesteMigracaoV47(unittest.TestCase):
    def test_fila_antiga_fica_com_o_caixa_que_existia(self):
        from src.database.esquema import VERSAO_ESQUEMA
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "loja.db")
            banco = BancoDados(caminho)
            banco.cfg_set("terminal", "3")
            banco.executar("INSERT INTO fila_impressao(criado_em, destino, nome, dados, status) "
                           "VALUES ('2026-11-01 10:00:00', 'caixa', 'cupom antigo', x'00', 'pendente')")
            banco.executar("ALTER TABLE fila_impressao DROP COLUMN terminal")
            banco.executar("PRAGMA user_version = 46")
            banco.fechar()
            banco = BancoDados(caminho)
            try:
                self.assertEqual(banco.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertEqual(banco.valor("SELECT terminal FROM fila_impressao WHERE nome = 'cupom antigo'"), 3)
                from src.controllers.fila_impressao_controller import FilaImpressao
                self.assertEqual(FilaImpressao(banco).contagem()["pendentes"], 1)
            finally:
                banco.fechar()


class TesteCodigo(unittest.TestCase):
    def test_codigo_vai_e_volta(self):
        chave = rede.nova_chave()
        codigo = rede.gerar_codigo(["192.168.0.10", "CAIXA-01"], 47811, chave)
        self.assertTrue(codigo.startswith(rede.PREFIXO_CODIGO))
        self.assertEqual(rede.ler_codigo(f"  {codigo[:20]}\n{codigo[20:]} "),
                         {"hosts": ["192.168.0.10", "CAIXA-01"], "porta": 47811, "chave": chave})

    def test_codigo_torto_explica(self):
        for texto in ("", "WILL1-abc", rede.PREFIXO_CODIGO + "!!!", rede.PREFIXO_CODIGO + "e30"):
            with self.assertRaises(ErroNegocio):
                rede.ler_codigo(texto)

    def test_salvar_e_remover_a_ligacao_deste_computador(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(rede, "RAIZ", pasta):
            self.assertIsNone(rede.ligacao_salva())
            codigo = rede.gerar_codigo(["192.168.0.10"], 47811, rede.nova_chave())
            with self.assertRaises(ErroNegocio):
                rede.salvar_ligacao(codigo, 1)
            primeira = rede.salvar_ligacao(codigo, 2)
            self.assertEqual(rede.ligacao_salva(), primeira)
            self.assertEqual(rede.caminho_da_ligacao(primeira), "pdv://192.168.0.10:47811")
            self.assertEqual(rede.salvar_ligacao(codigo, 3)["instalacao"], primeira["instalacao"])
            self.assertTrue(rede.remover_ligacao())
            self.assertFalse(rede.remover_ligacao())
            self.assertIsNone(rede.ligacao_salva())


if __name__ == "__main__":
    unittest.main()
