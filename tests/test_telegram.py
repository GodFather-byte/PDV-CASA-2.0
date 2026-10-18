"""Telegram do dono: pareamento por código, respostas dos botões, avisos do caixa e fila de envio (com um Telegram falso)."""
from __future__ import annotations

import os
import tempfile
import threading
import time
from unittest import mock

from src.controllers import notificacoes
from src.controllers.config_controller import CAMPOS_CONFIG
from src.controllers.telegram_controller import ServicoTelegram, TelegramController, normalizar_comando
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.conexao import BancoDados
from src.sync.telegram_api import ClienteTelegram, ErroTelegram
from tests.test_caixa import BaseCaixa

TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_0123456"
DONO, ESTRANHO = 1001, 2002


class TelegramFalso:
    """Faz o papel da internet: guarda o que o PDV mandou e entrega as mensagens que o dono 'digitou'."""

    def __init__(self):
        self.enviadas: list[tuple] = []         # (chat_id, texto, teclado)
        self.entrada: list[dict] = []
        self.falha = None                        # ErroTelegram a levantar em toda chamada, ou dict {'ok': False, ...}
        self.falha_chat: dict[int, dict] = {}    # chat_id -> resposta de erro só para esse chat
        self.token_valido = True
        self._n = 0

    def __call__(self, url, dados, timeout):
        metodo = url.rsplit("/", 1)[1]
        if self.falha:
            if isinstance(self.falha, Exception):
                raise self.falha
            return self.falha
        if metodo == "getMe":
            if not self.token_valido:
                return {"ok": False, "error_code": 401, "description": "Unauthorized"}
            return {"ok": True, "result": {"id": 7, "username": "casa_bot"}}
        if metodo == "sendMessage":
            if dados["chat_id"] in self.falha_chat:
                return self.falha_chat[dados["chat_id"]]
            self.enviadas.append((dados["chat_id"], dados["text"], dados.get("reply_markup")))
            return {"ok": True, "result": {}}
        if metodo == "getUpdates":
            novas, self.entrada = self.entrada, []
            return {"ok": True, "result": novas}
        raise AssertionError(metodo)

    def digitar(self, chat_id, texto, tipo="private", nome="Dono"):
        self._n += 1
        self.entrada.append({"update_id": 500 + self._n, "message": {
            "chat": {"id": chat_id, "type": tipo}, "from": {"first_name": nome}, "text": texto}})

    def textos(self, chat_id=None):
        return [t for c, t, _ in self.enviadas if chat_id is None or c == chat_id]


class BaseTelegram(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.tg_http = TelegramFalso()
        self.tg = TelegramController(self.banco, self.tg_http)

    def parear(self, chat_id=DONO):
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        self.tg_http.digitar(chat_id, f"/start {codigo}")
        self.tg.processar_atualizacoes(0)
        self.tg_http.enviadas.clear()

    def pergunta(self, texto, chat_id=DONO) -> str:
        self.tg_http.digitar(chat_id, texto)
        self.tg.processar_atualizacoes(0)
        return self.tg_http.enviadas[-1][1]

    def fila(self) -> list[str]:
        return [r["texto"] for r in self.banco.todos("SELECT texto FROM telegram_fila ORDER BY id")]

    def venda_fechada(self, valor_dinheiro=1600):
        vid = self.vender((self.skol, 2))
        self.pagar(vid, "Dinheiro", valor_dinheiro)
        self.caixa.fechar(vid)
        return vid


class TestePareamento(BaseTelegram):
    def test_token_malformado_ou_recusado_nao_e_guardado(self):
        with self.assertRaises(ErroNegocio):
            self.tg.salvar_token("isso nao e um token")
        self.tg_http.token_valido = False
        with self.assertRaisesRegex(ErroNegocio, "não aceitou"):
            self.tg.salvar_token(TOKEN)
        self.assertEqual(self.banco.cfg("telegram_token"), "")

    def test_token_valido_guarda_e_mostra_o_nome_do_bot(self):
        bot = self.tg.salvar_token(f"  {TOKEN}  ")
        self.assertEqual(bot["username"], "casa_bot")
        self.assertEqual((self.tg.token, self.tg.bot_usuario()), (TOKEN, "casa_bot"))

    def test_codigo_exige_token_e_tem_6_digitos(self):
        with self.assertRaises(ErroNegocio):
            self.tg.gerar_codigo()
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        self.assertRegex(codigo, r"^\d{6}$")
        self.assertEqual(self.tg.codigo_pendente(), codigo)

    def test_codigo_certo_autoriza_liga_o_telegram_e_manda_o_teclado(self):
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        self.tg_http.digitar(DONO, f"/start {codigo}", nome="Carlos")
        self.tg.processar_atualizacoes(0)
        self.assertEqual([(c["chat_id"], c["nome"]) for c in self.tg.chats()], [(DONO, "Carlos")])
        self.assertTrue(self.banco.cfg_bool("telegram_ativo"))
        chat, texto, teclado = self.tg_http.enviadas[-1]
        self.assertIn("Conectado", texto)
        botoes = [b["text"] for linha in teclado["keyboard"] for b in linha]
        self.assertIn("📊 Resumo", botoes)
        self.assertIn("❌ Cancelamentos", botoes)
        self.assertIsNone(self.tg.codigo_pendente())                # o código é de uso único

    def test_codigo_nao_serve_duas_vezes_nem_para_outro_celular(self):
        self.parear()
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        self.tg_http.digitar(DONO, f"/start {codigo}")
        self.tg_http.digitar(ESTRANHO, f"/start {codigo}")
        self.tg.processar_atualizacoes(0)
        self.assertEqual({c["chat_id"] for c in self.tg.chats()}, {DONO})
        self.assertIn("inválido", self.tg_http.textos(ESTRANHO)[-1])

    def test_codigo_errado_cinco_vezes_invalida_o_certo(self):
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        for tentativa in range(5):
            self.tg_http.digitar(ESTRANHO, f"/start {(int(codigo) + 1 + tentativa) % 10 ** 6:06d}")
        self.tg_http.digitar(ESTRANHO, f"/start {codigo}")
        self.tg.processar_atualizacoes(0)
        self.assertEqual(self.tg.chats(), [])
        self.assertIsNone(self.tg.codigo_pendente())

    def test_codigo_vence_em_10_minutos(self):
        self.tg.salvar_token(TOKEN)
        codigo = self.tg.gerar_codigo()
        self.avancar(minutes=11)
        self.tg_http.digitar(DONO, f"/start {codigo}")
        self.tg.processar_atualizacoes(0)
        self.assertEqual(self.tg.chats(), [])

    def test_estranho_nao_recebe_dado_nenhum(self):
        self.parear()
        self.venda_fechada()
        for texto in ("📊 Resumo", "/caixa", "/start", "qualquer coisa"):
            resposta = self.pergunta(texto, ESTRANHO)
            self.assertIn("privado", resposta)
            self.assertNotIn("R$", resposta)

    def test_grupo_e_mensagem_sem_texto_sao_ignorados(self):
        self.parear()
        self.tg_http.digitar(DONO, "📊 Resumo", tipo="group")
        self.tg_http.entrada.append({"update_id": 900, "message": {"chat": {"id": DONO, "type": "private"}, "photo": []}})
        self.tg.processar_atualizacoes(0)
        self.assertEqual(self.tg_http.enviadas, [])

    def test_trocar_de_bot_apaga_os_celulares_pareados(self):
        self.parear()
        self.tg.salvar_token("987654321:ZYXwvuTSRqponMLKjihGFEdcba_9876543")
        self.assertEqual(self.tg.chats(), [])

    def test_remover_celular(self):
        self.parear()
        self.tg.remover_chat(DONO)
        self.assertEqual(self.tg.chats(), [])
        self.assertIn("privado", self.pergunta("📊 Resumo"))

    def test_offset_avanca_e_nao_repete_mensagem(self):
        self.parear()
        self.pergunta("📊 Resumo")
        self.assertGreater(self.banco.cfg_int("telegram_offset"), 0)


class TesteRespostas(BaseTelegram):
    def setUp(self):
        super().setUp()
        self.parear()

    def test_comandos_aceitam_botao_barra_e_texto(self):
        for texto in ("📊 Resumo", "/resumo", "resumo", "/resumo@casa_bot", "RESUMO"):
            self.assertEqual(normalizar_comando(texto), "resumo", texto)
        self.assertEqual(normalizar_comando("🍺 Mais vendidos"), "top")
        self.assertEqual(normalizar_comando("/ajuda"), "ajuda")
        self.assertIsNone(normalizar_comando("bom dia"))

    def test_texto_desconhecido_reapresenta_os_botoes(self):
        self.pergunta("bom dia")
        _, texto, teclado = self.tg_http.enviadas[-1]
        self.assertIn("Não entendi", texto)
        self.assertTrue(teclado)

    def test_resumo_com_vendas_formas_e_diferenca(self):
        self.venda_fechada()
        vid = self.vender((self.agua, 2))
        self.pagar(vid, "Pix", 700)
        self.caixa.fechar(vid)
        r = self.pergunta("📊 Resumo")
        self.assertIn("Faturamento: R$ 23,00", r)
        self.assertIn("Vendas: 2", r)
        self.assertIn("Dinheiro: R$ 16,00", r)
        self.assertIn("Pix: R$ 7,00", r)

    def test_resumo_sem_vendas(self):
        self.assertIn("Nenhuma venda", self.pergunta("📊 Resumo"))

    def test_caixa_aberto_mostra_dinheiro_esperado(self):
        self.venda_fechada()
        r = self.pergunta("💵 Caixa")
        self.assertIn("turno 1", r)
        self.assertIn("Dinheiro que deveria estar na gaveta: R$ 116,00", r)      # fundo 100 + venda 16

    def test_caixa_fechado_mostra_o_ultimo_fechamento(self):
        self.turnos.fechar(self.turno, self.adm, 9000)
        r = self.pergunta("💵 Caixa")
        self.assertIn("Nenhum caixa aberto", r)
        self.assertIn("faltou R$ 10,00", r)

    def test_mais_vendidos_ordena_por_valor(self):
        self.venda_fechada()
        vid = self.vender((self.agua, 1))
        self.pagar(vid, "Pix", 350)
        self.caixa.fechar(vid)
        r = self.pergunta("🍺 Mais vendidos").splitlines()
        self.assertTrue(r[2].startswith("1. SKOL — 2 un"))
        self.assertTrue(r[3].startswith("2. AGUA — 1 un"))

    def test_estoque_lista_zerados_e_no_ponto_de_pedido(self):
        self.novo_produto("GIN", 3000, estoque=True, qt=0)
        ponto = self.novo_produto("VODKA", 2500, estoque=True, qt=3)
        self.banco.executar("UPDATE produtos SET estoque_minimo = 5 WHERE id = ?", (ponto,))
        r = self.pergunta("📦 Estoque")
        self.assertIn("Sem estoque (1)", r)
        self.assertIn("GIN", r)
        self.assertIn("VODKA: 3 (mín. 5)", r)
        self.assertNotIn("SKOL", r)

    def test_estoque_sem_produto_controlado(self):
        self.banco.executar("UPDATE produtos SET controla_estoque = 0")
        self.assertIn("Nenhum produto com controle", self.pergunta("📦 Estoque"))

    def test_abertas_lista_comandas_com_consumo(self):
        vid, _ = self.caixa.abrir_mesa(45, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 3)
        r = self.pergunta("🪑 Abertas")
        self.assertIn("Em aberto agora: 1", r)
        self.assertIn("R$ 26,40", r)                        # 3 x R$ 8,00 + 10% de serviço da comanda
        self.assertNotIn("R$ 0,00", r)

    def test_cancelamentos_mostra_cupom_item_motivo_e_operador(self):
        vid = self.vender((self.skol, 1))
        self.caixa.cancelar_venda(vid, "cliente desistiu")
        vid2 = self.vender((self.skol, 2))
        item = self.banco.valor("SELECT id FROM itens_venda WHERE venda_id = ?", (vid2,))
        self.caixa.cancelar_item(item, "errei o pedido")
        r = self.pergunta("❌ Cancelamentos")
        self.assertIn("cliente desistiu", r)
        self.assertIn("ADM", r)
        self.assertIn("2x SKOL", r)

    def test_cancelamentos_sem_nada(self):
        self.assertIn("Nenhum cancelamento", self.pergunta("❌ Cancelamentos"))

    def test_ontem_usa_a_noite_anterior(self):
        self.venda_fechada()
        self.avancar(days=1)
        self.assertIn("Nenhuma venda", self.pergunta("📊 Resumo"))
        self.assertIn("Faturamento: R$ 16,00", self.pergunta("📅 Ontem"))

    def test_desligado_no_pdv_o_bot_nao_responde_dados(self):
        self.banco.cfg_set("telegram_ativo", "N")
        self.assertIn("desligado", self.pergunta("📊 Resumo"))

    def test_resposta_com_erro_interno_nao_derruba_o_bot(self):
        with mock.patch("src.controllers.telegram_textos.resumo", side_effect=RuntimeError("quebrou")):
            self.assertIn("Não consegui", self.pergunta("📊 Resumo"))
        self.assertIn("Nenhuma venda", self.pergunta("📊 Resumo"))          # e a próxima pergunta funciona


class TesteAvisosDoCaixa(BaseTelegram):
    def test_desligado_nao_grava_nada(self):
        self.venda_fechada()
        self.turnos.fechar(self.turno, self.adm, 11600)
        self.assertEqual(self.fila(), [])

    def test_ligado_sem_celular_pareado_nao_grava(self):
        self.banco.cfg_set("telegram_ativo", "S")
        self.banco.cfg_set("telegram_token", TOKEN)
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.assertEqual(self.fila(), [])

    def test_abertura_e_fechamento_do_caixa(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.parear()
        t = self.turnos.abrir(self.adm, 2, 5000)
        self.venda_fechada()
        self.turnos.fechar(t, self.adm, 6000)                       # esperado 50 + 16 = 66; contou 60
        abertura, fechamento = self.fila()
        self.assertIn("Caixa aberto — turno 2", abertura)
        self.assertIn("Fundo de caixa: R$ 50,00", abertura)
        self.assertIn("Caixa fechado — turno 2", fechamento)
        self.assertIn("Dinheiro esperado: R$ 66,00", fechamento)
        self.assertIn("Dinheiro contado: R$ 60,00", fechamento)
        self.assertIn("faltou R$ 6,00", fechamento)

    def test_fechamento_que_bate(self):
        self.parear()
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.assertIn("caixa bateu certinho", self.fila()[-1])

    def test_cupom_cancelado_leva_motivo_e_quem_cancelou(self):
        self.parear()
        vid = self.vender((self.skol, 2))
        self.caixa.cancelar_venda(vid, "cliente foi embora")
        (aviso,) = self.fila()
        self.assertIn("Cupom cancelado", aviso)
        self.assertIn("R$ 16,00", aviso)
        self.assertIn("Por: ADM", aviso)
        self.assertIn("Motivo: cliente foi embora", aviso)

    def test_cancelar_venda_vazia_nao_avisa(self):
        self.parear()
        self.caixa.cancelar_venda(self.caixa.abrir_balcao())
        self.assertEqual(self.fila(), [])

    def test_item_cancelado_sem_motivo_diz_que_nao_foi_informado(self):
        self.parear()
        vid = self.vender((self.skol, 3))
        self.caixa.cancelar_item(self.banco.valor("SELECT id FROM itens_venda WHERE venda_id = ?", (vid,)))
        (aviso,) = self.fila()
        self.assertIn("3x SKOL", aviso)
        self.assertIn("Motivo: não informado", aviso)

    def test_sangria_e_suprimento(self):
        self.parear()
        self.turnos.movimentar(self.turno, self.adm, "saida", 5000, "fornecedor de gelo")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 1000)
        sangria, suprimento = self.fila()
        self.assertIn("Sangria: R$ 50,00", sangria)
        self.assertIn("fornecedor de gelo", sangria)
        self.assertIn("Suprimento: R$ 10,00", suprimento)

    def test_cada_tipo_de_aviso_pode_ser_desligado(self):
        self.parear()
        for chave in ("turno", "cancelamento", "item", "sangria"):
            self.banco.cfg_set(f"telegram_avisa_{chave}", "N")
        vid = self.vender((self.skol, 1))
        self.caixa.cancelar_item(self.banco.valor("SELECT id FROM itens_venda WHERE venda_id = ?", (vid,)))
        self.caixa.cancelar_venda(vid, "x")
        self.turnos.movimentar(self.turno, self.adm, "saida", 100)
        self.turnos.fechar(self.turno, self.adm, 9900)
        self.assertEqual(self.fila(), [])

    def test_falha_ao_montar_o_aviso_nunca_derruba_o_caixa(self):
        self.parear()
        self.banco.executar("DROP TABLE telegram_fila")
        vid = self.vender((self.skol, 1))
        self.caixa.cancelar_venda(vid, "x")                         # não levanta, mesmo sem a tabela da fila
        self.assertEqual(self.banco.valor("SELECT status FROM vendas WHERE id = ?", (vid,)), "cancelada")

    def test_backup_automatico_que_falha_avisa(self):
        self.parear()
        from src.controllers.utilitario_controller import UtilitarioController
        util = UtilitarioController(self.banco)
        util.backup = lambda: (_ for _ in ()).throw(OSError("disco cheio"))
        self.assertIsNone(util.backup_automatico("teste"))
        (aviso,) = self.fila()
        self.assertIn("backup automático do PDV falhou", aviso)
        self.assertIn("disco cheio", aviso)

    def test_nenhum_aviso_leva_dado_de_cliente(self):
        self.parear()
        cliente = self.cliente("MARIA SILVA")
        vid = self.caixa.abrir_caderneta(cliente)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.caixa.cancelar_venda(vid, "teste")
        self.assertNotIn("MARIA", "\n".join(self.fila()))


class TesteFilaDeEnvio(BaseTelegram):
    def setUp(self):
        super().setUp()
        self.parear()

    def test_envia_na_ordem_e_marca_como_enviado(self):
        notificacoes.enfileirar(self.banco, "turno", "primeiro")
        notificacoes.enfileirar(self.banco, "turno", "segundo")
        self.assertEqual(self.tg.processar_fila(), 2)
        self.assertEqual(self.tg_http.textos(), ["primeiro", "segundo"])
        self.assertEqual(self.tg.processar_fila(), 0)

    def test_sem_internet_o_aviso_espera_e_sai_quando_volta(self):
        notificacoes.enfileirar(self.banco, "turno", "aviso")
        self.tg_http.falha = ErroTelegram("Sem conexão com o Telegram.")
        with self.assertRaises(ErroTelegram):
            self.tg.processar_fila()
        linha = self.banco.um("SELECT status, tentativas FROM telegram_fila")
        self.assertEqual((linha["status"], linha["tentativas"]), ("pendente", 1))
        self.assertIn("Sem conexão", self.tg.ultimo_erro())
        self.tg_http.falha = None
        self.assertEqual(self.tg.processar_fila(), 1)
        self.assertEqual(self.tg.ultimo_erro(), "")

    def test_varios_celulares_sem_repetir_para_quem_ja_recebeu(self):
        self.tg_http.digitar(ESTRANHO, "x")
        self.banco.executar("INSERT INTO telegram_chats(chat_id, nome, criado_em) VALUES (?,?,?)", (ESTRANHO, "Sócio", "2026-10-03 21:00:00"))
        self.tg_http.falha_chat[ESTRANHO] = {"ok": False, "error_code": 502, "description": "Bad Gateway"}
        notificacoes.enfileirar(self.banco, "turno", "aviso")
        with self.assertRaises(ErroTelegram):
            self.tg.processar_fila()
        self.assertEqual(self.tg_http.textos(DONO), ["aviso"])
        self.tg_http.falha_chat.clear()
        self.tg.processar_fila()
        self.assertEqual(self.tg_http.textos(DONO), ["aviso"])         # o dono não recebe em dobro
        self.assertEqual(self.tg_http.textos(ESTRANHO), ["aviso"])

    def test_quem_bloqueou_o_bot_sai_da_lista(self):
        self.tg_http.falha_chat[DONO] = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
        notificacoes.enfileirar(self.banco, "turno", "aviso")
        self.tg.processar_fila()
        self.assertEqual(self.tg.chats(), [])

    def test_token_recusado_nao_fica_insistindo_no_mesmo_aviso(self):
        notificacoes.enfileirar(self.banco, "turno", "aviso")
        self.tg_http.falha = {"ok": False, "error_code": 401, "description": "Unauthorized"}
        with self.assertRaises(ErroTelegram):
            self.tg.processar_fila()
        self.assertEqual(self.banco.valor("SELECT status FROM telegram_fila"), "erro")

    def test_aviso_velho_demais_vira_erro_em_vez_de_chegar_atrasado(self):
        notificacoes.enfileirar(self.banco, "turno", "velho")
        self.avancar(hours=49)
        self.assertEqual(self.tg.processar_fila(), 0)
        self.assertEqual(self.tg_http.textos(), [])
        self.assertEqual(self.banco.valor("SELECT status FROM telegram_fila"), "erro")

    def test_testar_envia_para_todos(self):
        self.assertEqual(self.tg.testar(), 1)
        self.assertIn("Teste do PDV", self.tg_http.textos()[-1])

    def test_testar_sem_celular_explica(self):
        self.tg.remover_chat(DONO)
        with self.assertRaisesRegex(ErroNegocio, "Nenhum celular"):
            self.tg.testar()

    def test_testar_com_erro_vira_mensagem_para_o_operador(self):
        self.tg_http.falha = ErroTelegram("Sem conexão com o Telegram.")
        with self.assertRaisesRegex(ErroNegocio, "Sem conexão"):
            self.tg.testar()


class TesteResumoDaManha(BaseTelegram):
    def setUp(self):
        super().setUp()
        self.parear()
        self.venda_fechada()                                  # sábado 03/10 21:00: noite de 03/10

    def passar_para(self, dia_hora):
        self.avancar(seconds=(dia_hora - self._hora["t"]).total_seconds())

    def test_envia_uma_vez_por_dia_no_horario(self):
        from datetime import datetime
        self.banco.cfg_set("telegram_ultimo_resumo", "2026-10-02")
        self.passar_para(datetime(2026, 10, 4, 6, 59))
        self.assertFalse(self.tg.resumo_agendado())            # ainda não deu 07:00
        self.passar_para(datetime(2026, 10, 4, 7, 0))
        self.assertTrue(self.tg.resumo_agendado())
        self.assertFalse(self.tg.resumo_agendado())            # de novo no mesmo dia: não
        (texto,) = self.fila()
        self.assertIn("Resumo da noite — sáb 03/10", texto)
        self.assertIn("Faturamento: R$ 16,00", texto)

    def test_nunca_antes_da_virada_do_dia(self):
        from datetime import datetime
        self.banco.cfg_set("telegram_ultimo_resumo", "2026-10-02")
        self.banco.cfg_set("telegram_resumo_hora", "03:00")        # a noite ainda não acabou às 3h (a virada é às 6h)
        self.passar_para(datetime(2026, 10, 4, 3, 30))
        self.assertFalse(self.tg.resumo_agendado())
        self.passar_para(datetime(2026, 10, 4, 6, 0))
        self.assertTrue(self.tg.resumo_agendado())

    def test_horario_vazio_desliga(self):
        from datetime import datetime
        self.banco.cfg_set("telegram_resumo_hora", "")
        self.passar_para(datetime(2026, 10, 4, 9, 0))
        self.assertFalse(self.tg.resumo_agendado())

    def test_primeiro_resumo_depois_do_pareamento_e_o_da_proxima_manha(self):
        from datetime import datetime
        self.assertEqual(self.banco.cfg("telegram_ultimo_resumo"), "2026-10-02")   # pareou no dia 03: já conta 02 como enviado
        self.passar_para(datetime(2026, 10, 3, 15, 0))
        self.assertFalse(self.tg.resumo_agendado())

    def test_horario_da_configuracao_e_validado(self):
        from src.controllers.config_controller import ConfigController
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"telegram_resumo_hora": "7"})
        self.assertEqual(self.banco.cfg("telegram_resumo_hora"), "07:00")
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"telegram_resumo_hora": "25:99"})

    def test_resumo_da_manha_avisa_produto_sem_estoque(self):
        self.novo_produto("GIN", 3000, estoque=True, qt=0)
        self.assertIn("Produtos sem estoque: 1", self.tg.responder_comando("ontem"))


class TesteConfiguracaoDoTelegram(BaseTelegram):
    def test_token_nao_aparece_no_formulario_geral(self):
        self.assertNotIn("telegram_token", [c[0] for c in CAMPOS_CONFIG])
        self.assertIn("telegram_ativo", [c[0] for c in CAMPOS_CONFIG])

    def test_modulo_de_acesso_existe_e_e_do_dono(self):
        self.assertEqual(self.banco.valor("SELECT nivel FROM acessos WHERE modulo = 'cfg_telegram'"), 4)


class TesteApiTelegram(BaseTelegram):
    def test_erro_nao_vaza_o_token(self):
        def http(url, dados, timeout):
            return {"ok": False, "error_code": 401, "description": "Unauthorized"}
        with self.assertRaises(ErroTelegram) as e:
            ClienteTelegram(TOKEN, http).quem_sou()
        self.assertNotIn(TOKEN, str(e.exception))
        self.assertTrue(e.exception.definitivo)

    def test_sem_token_nao_chama_a_rede(self):
        def http(url, dados, timeout):
            raise AssertionError("não devia chamar a rede")
        with self.assertRaises(ErroTelegram):
            ClienteTelegram("", http).quem_sou()

    def test_texto_longo_e_cortado_no_limite_do_telegram(self):
        vistos = []
        ClienteTelegram(TOKEN, lambda u, d, t: vistos.append(d) or {"ok": True, "result": {}}).enviar(1, "x" * 5000)
        self.assertEqual(len(vistos[0]["text"]), 4096)


class TesteHttpReal(BaseTelegram):
    """O caminho de rede de verdade (urllib), contra um servidorzinho local que imita a Bot API."""

    def setUp(self):
        super().setUp()
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer

        recebidos = self.recebidos = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                recebidos.append((self.path, corpo))
                if "/botRUIM:" in self.path:
                    status, resposta = 401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
                elif self.path.endswith("/sendMessage"):
                    status, resposta = 200, {"ok": True, "result": {"message_id": 1}}
                else:
                    status, resposta = 200, {"ok": True, "result": {"id": 7, "username": "casa_bot"}}
                dados = json.dumps(resposta).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *a):
                pass

        self.servidor = HTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.servidor.server_close)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.shutdown)
        base = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        for alvo, valor in (("src.sync.telegram_api.URL_BASE", base),):
            patcher = mock.patch(alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_resposta_ok_e_envio(self):
        c = ClienteTelegram(TOKEN)
        self.assertEqual(c.quem_sou()["username"], "casa_bot")
        c.enviar(55, "oi", [["📊 Resumo"]])
        caminho, corpo = self.recebidos[-1]
        self.assertTrue(caminho.endswith(f"/bot{TOKEN}/sendMessage"))
        self.assertEqual((corpo["chat_id"], corpo["text"]), (55, "oi"))
        self.assertEqual(corpo["reply_markup"]["keyboard"], [[{"text": "📊 Resumo"}]])

    def test_http_401_com_corpo_json_vira_erro_definitivo_sem_vazar_o_token(self):
        ruim = "RUIM:ABCdefGHIjklMNOpqrSTUvwxYZ_0123456"
        with self.assertRaises(ErroTelegram) as e:
            ClienteTelegram(ruim).quem_sou()
        self.assertEqual(e.exception.codigo, 401)
        self.assertTrue(e.exception.definitivo)
        self.assertNotIn(ruim, str(e.exception))

    def test_servidor_fora_do_ar_vira_erro_de_conexao_sem_vazar_o_token(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        with self.assertRaises(ErroTelegram) as e:
            ClienteTelegram(TOKEN).quem_sou()
        self.assertIsNone(e.exception.codigo)
        self.assertFalse(e.exception.definitivo)
        self.assertNotIn(TOKEN, str(e.exception))


class TesteServicoEmSegundoPlano(BaseTelegram):
    """As duas threads de verdade, com banco em arquivo e o Telegram falso."""

    def test_aviso_gravado_no_caixa_chega_ao_celular_e_botao_e_respondido(self):
        pasta = tempfile.mkdtemp(prefix="pdv_tg_")
        self.addCleanup(lambda: __import__("shutil").rmtree(pasta, ignore_errors=True))
        caminho = os.path.join(pasta, "loja.db")
        banco = BancoDados(caminho)
        self.addCleanup(banco.fechar)
        http = TelegramFalso()
        ctl = TelegramController(banco, http)
        ctl.salvar_token(TOKEN)
        codigo = ctl.gerar_codigo()
        servico = ServicoTelegram(caminho, http)
        servico.iniciar()
        self.addCleanup(servico.parar)
        http.digitar(DONO, f"/start {codigo}")
        self._esperar(lambda: ctl.chats())
        notificacoes.enfileirar(banco, "turno", "🔴 aviso de teste")
        self._esperar(lambda: "🔴 aviso de teste" in http.textos(DONO))
        http.digitar(DONO, "🪑 Abertas")
        self._esperar(lambda: any("Nenhuma mesa" in t for t in http.textos(DONO)))

    @staticmethod
    def _esperar(condicao, limite=8.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if condicao():
                return
            time.sleep(0.05)
        raise AssertionError("o serviço do Telegram não reagiu a tempo")

    def test_servico_exige_banco_em_arquivo(self):
        with self.assertRaises(ErroNegocio):
            ServicoTelegram(":memory:")


class TesteConsultasCompletas(BaseTelegram):
    """O dono consulta 'tudo' pelo celular: semana, mês, hora, equipe, contas, caderneta, compras, produto e mesa."""

    def setUp(self):
        super().setUp()
        self.parear()

    def test_novos_botoes_existem_no_teclado(self):
        from src.controllers.telegram_controller import TECLADO
        botoes = [b for linha in TECLADO for b in linha]
        for esperado in ("📈 Semana", "🗓️ Mês", "🕐 Por hora", "👥 Equipe", "💳 Contas", "📒 Caderneta", "🛒 Comprar", "🔎 Produto"):
            self.assertIn(esperado, botoes)
        self.assertEqual(len(botoes), len(set(botoes)))

    def test_interpretar_comandos_com_argumento(self):
        from src.controllers.telegram_controller import interpretar
        self.assertEqual(interpretar("produto skol lata"), ("produto", "skol lata"))
        self.assertEqual(interpretar("/produto@casa_bot skol"), ("produto", "skol"))
        self.assertEqual(interpretar("mesa 12"), ("mesa", "M12"))
        self.assertEqual(interpretar("Comanda 5"), ("mesa", "C5"))
        self.assertEqual(interpretar("📈 Semana"), ("semana", ""))
        self.assertEqual(interpretar("mesa"), ("mesa", ""))
        self.assertIsNone(interpretar("bom dia"))
        self.assertIsNone(interpretar("mesa abc"))

    def test_semana_soma_os_dias_e_destaca_o_melhor(self):
        self.venda_fechada()                                       # hoje: R$ 16,00
        self.avancar(days=1)
        self.turnos.fechar(self.turno, self.adm, 11600)
        self.turnos.abrir(self.adm, 1, 0)
        vid = self.vender((self.skol, 5))
        self.pagar(vid, "Dinheiro", 4000)
        self.caixa.fechar(vid)                                     # amanhã: R$ 40,00
        r = self.pergunta("📈 Semana")
        self.assertIn("Total: R$ 56,00 em 2 vendas", r)
        self.assertIn("R$ 40,00 · 1 vendas (até agora) 🏆", r)
        self.assertIn("R$ 0,00 · 0 vendas", r)

    def test_semana_e_mes_sem_vendas(self):
        self.assertIn("Nenhuma venda", self.pergunta("📈 Semana"))
        self.assertIn("Nenhuma venda neste mês", self.pergunta("🗓️ Mês"))

    def test_mes_compara_com_o_mes_anterior(self):
        self.venda_fechada()                                       # 03/10: R$ 16,00
        r = self.pergunta("🗓️ Mês")
        self.assertIn("Outubro até hoje", r)
        self.assertIn("Faturamento: R$ 16,00", r)
        self.assertIn("Melhor dia", r)
        self.assertNotIn("Mês anterior", r)                        # sem vendas em setembro, não há o que comparar

    def test_por_hora_mostra_o_pico(self):
        self.venda_fechada()
        r = self.pergunta("🕐 Por hora")
        self.assertIn("21h", r)
        self.assertIn("Pico: 21h com R$ 16,00", r)

    def test_equipe_agrupa_por_quem_vendeu(self):
        self.venda_fechada()
        r = self.pergunta("👥 Equipe")
        self.assertIn("1. ADM: R$ 16,00 · 1 vendas", r)

    def test_contas_vencidas_e_proximas(self):
        self.assertIn("desligado", self.pergunta("💳 Contas"))
        self.banco.cfg_set("usar_contas", "S")
        self.assertIn("Nada vencido", self.pergunta("💳 Contas"))
        sub = self.banco.valor("SELECT sp.id FROM subplanos sp JOIN planos_contas pl ON pl.id = sp.plano_id WHERE pl.debito = 1 LIMIT 1")
        from src.controllers.contas_controller import ContasController
        c = ContasController(self.banco)
        c.incluir(sub, "Aluguel", self.tipo("Dinheiro"), 250000, "01/10/2026")
        c.incluir(sub, "Luz", self.tipo("Dinheiro"), 40000, "05/10/2026")
        r = self.pergunta("💳 Contas")
        self.assertIn("Vencidas (1, R$ 2.500,00)", r)
        self.assertIn("próximos 7 dias (1, R$ 400,00)", r)

    def test_caderneta_lista_devedores_sem_dados_pessoais(self):
        self.assertIn("Ninguém está devendo", self.pergunta("📒 Caderneta"))
        joao = self.cliente("JOAO", 50000)
        self.banco.executar("UPDATE clientes SET saldo_cent = -12000, cpf = '12345678900', telefone = '1199999' WHERE id = ?", (joao,))
        r = self.pergunta("📒 Caderneta")
        self.assertIn("1 clientes devendo, total R$ 120,00", r)
        self.assertIn("1. JOAO: R$ 120,00", r)
        self.assertNotIn("12345678900", r)
        self.assertNotIn("1199999", r)

    def test_comprar_usa_o_estoque_minimo(self):
        self.assertIn("Nada para repor", self.pergunta("🛒 Comprar"))
        self.banco.executar("UPDATE produtos SET estoque_minimo = 60, qt_atual = 10 WHERE id = ?", (self.skol,))
        r = self.pergunta("🛒 Comprar")
        self.assertIn("SKOL: tem 10, comprar 110 UN", r)

    def test_produto_por_comando_e_por_nome_solto(self):
        self.banco.executar("UPDATE produtos SET estoque_minimo = 20 WHERE id = ?", (self.skol,))
        self.venda_fechada()
        for texto in ("produto skol", "skol", "preço SKOL"):
            r = self.pergunta(texto)
            self.assertIn("🔎 SKOL", r, texto)
            self.assertIn("Preço de venda: R$ 8,00", r)
            self.assertIn("Estoque: 98 (✅ normal)", r)
            self.assertIn("Venda -2 → 98", r)
        self.assertIn("Não achei", self.pergunta("produto zzzz"))
        self.assertIn("Não entendi", self.pergunta("zzzz"))
        self.assertIn("Digite o nome", self.pergunta("🔎 Produto"))
        self.assertIn("Não controla estoque", self.pergunta("produto agua"))

    def test_produto_com_varios_resultados_lista_os_nomes(self):
        self.novo_produto("SKOL LATA", 900)
        r = self.pergunta("produto sko")
        self.assertIn("2 produtos combinam", r)
        self.assertIn("SKOL LATA — R$ 9,00", r)
        self.assertIn("🔎 SKOL\n", self.pergunta("produto skol"))             # nome exato vence os parecidos

    def test_mesa_mostra_itens_e_total(self):
        vid, _ = self.caixa.abrir_mesa(12)
        self.caixa.adicionar_item(vid, self.skol, 3)
        r = self.pergunta("mesa 12")
        self.assertIn("Mesa 12", r)
        self.assertIn("3x SKOL: R$ 24,00", r)
        self.assertIn("Total até agora", r)
        self.assertIn("não está aberta", self.pergunta("mesa 99"))
        self.assertIn("Digite o número", self.pergunta("mesa"))

    def test_resumo_da_manha_avisa_contas_do_dia(self):
        self.banco.cfg_set("usar_contas", "S")
        sub = self.banco.valor("SELECT sp.id FROM subplanos sp JOIN planos_contas pl ON pl.id = sp.plano_id WHERE pl.debito = 1 LIMIT 1")
        from src.controllers.contas_controller import ContasController
        ContasController(self.banco).incluir(sub, "Gelo", self.tipo("Dinheiro"), 30000, "03/10/2026")
        self.venda_fechada()
        from src.controllers import telegram_textos as textos
        r = textos.resumo(self.banco, fechado=True)
        self.assertIn("Contas a pagar hoje: 1 (R$ 300,00)", r)


class TesteAvisosEmTempoReal(BaseTelegram):
    def test_aviso_de_cada_venda_nasce_desligado_e_liga_pela_configuracao(self):
        self.parear()
        self.venda_fechada()
        self.assertEqual(self.fila(), [])
        self.banco.cfg_set("telegram_avisa_venda", "S")
        self.venda_fechada()
        (aviso,) = self.fila()
        self.assertIn("Venda — balcão: R$ 16,00", aviso)
        self.assertIn("Dinheiro R$ 16,00", aviso)
        self.assertIn("Por: ADM", aviso)

    def test_instalacao_antiga_sem_a_chave_tambem_nao_avisa_cada_venda(self):
        self.parear()
        self.banco.executar("DELETE FROM config WHERE chave = 'telegram_avisa_venda'")
        self.venda_fechada()
        self.assertEqual(self.fila(), [])

    def test_avisa_quando_produto_acaba_e_so_na_hora_que_cruza(self):
        self.parear()
        self.banco.executar("UPDATE produtos SET qt_atual = 3, estoque_minimo = 2 WHERE id = ?", (self.skol,))
        vid = self.vender((self.skol, 1))                           # 3 -> 2: entra no ponto de pedido
        self.pagar(vid, "Dinheiro", 800); self.caixa.fechar(vid)
        vid = self.vender((self.skol, 1))                           # 2 -> 1: continua no ponto, sem aviso novo
        self.pagar(vid, "Dinheiro", 800); self.caixa.fechar(vid)
        vid = self.vender((self.skol, 1))                           # 1 -> 0: acabou
        self.pagar(vid, "Dinheiro", 800); self.caixa.fechar(vid)
        vid = self.vender((self.skol, 1))                           # já zerado: sem aviso repetido
        self.pagar(vid, "Dinheiro", 800); self.caixa.fechar(vid)
        avisos = self.fila()
        self.assertEqual(len(avisos), 2)
        self.assertIn("SKOL está acabando: restam 2 (mínimo 2)", avisos[0])
        self.assertIn("SKOL ACABOU", avisos[1])

    def test_aviso_de_estoque_pode_ser_desligado(self):
        self.parear()
        self.banco.cfg_set("telegram_avisa_estoque", "N")
        self.banco.executar("UPDATE produtos SET qt_atual = 1 WHERE id = ?", (self.skol,))
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800); self.caixa.fechar(vid)
        self.assertEqual(self.fila(), [])

    def test_novas_opcoes_aparecem_na_configuracao(self):
        chaves = [c[0] for c in CAMPOS_CONFIG]
        self.assertIn("telegram_avisa_venda", chaves)
        self.assertIn("telegram_avisa_estoque", chaves)
