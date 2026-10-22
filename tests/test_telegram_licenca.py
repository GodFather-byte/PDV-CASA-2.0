"""Painel do dono no Telegram: licença, suporte, pedido de renovação e avisos de vencimento.

Tudo com Telegram falso, banco em memória, relógio controlado e chave de TESTE (nunca a chave real), sem rede.
"""
from __future__ import annotations

import sys
import types
from datetime import date, datetime

from src.controllers import notificacoes
from src.controllers.telegram_controller import (BOTOES, CHAVE_AVISO_LICENCA, TECLADO, TelegramController,
                                                 normalizar_comando)
from src.core import ed25519, licenca
from src.core.erros import ErroNegocio
from tests.test_telegram import DONO, ESTRANHO, BaseTelegram

SEMENTE_TESTE = bytes(range(32))           # par de chaves só de teste
LOJA = "LOJA-TESTE"
HOJE = date(2026, 10, 3)                   # mesmo dia do relógio fixo de BaseTeste
CLIENTE_SECRETO = "ZULMIRA DEVEDORA"


_SEM_RESPOSTA = object()


class PonteFalsa(types.ModuleType):
    """Faz o papel de src.sync.ponte seguindo o contrato dela: `estado(banco)` é local (dict) e
    `solicitar_renovacao(banco, http=None)` devolve o id do pedido; sem rede o pedido fica 'pendente' (não levanta);
    ponte desligada ou mal configurada levanta ErroNegocio. Registra as chamadas; nunca usa rede."""

    def __init__(self, entrega="enviada", falha_pedido=None, resposta=_SEM_RESPOSTA, ativa=True, falha_estado=None, **estado):
        super().__init__("src.sync.ponte")
        self.chamadas: list[tuple] = []
        self.entrega, self.falha_pedido, self.resposta, self.falha_estado = entrega, falha_pedido, resposta, falha_estado
        self.dados = {"ativa": ativa, "caixa_id": "CX-TESTE", "token_configurado": True, "ultimo_sucesso": "",
                      "ultima_tentativa": "", "erro": "", "licenca_aplicada_id": "", "licenca_erro": "",
                      "solicitacao_id": "", "solicitacao_estado": ""}
        self.novo_ciclo = True
        self.dados.update(estado)

    def estado(self, banco):
        if self.falha_estado:
            raise self.falha_estado
        return dict(self.dados)

    def solicitar_renovacao(self, banco, http=None):
        self.chamadas.append((banco, http))
        if self.falha_pedido:
            raise self.falha_pedido
        if self.resposta is not _SEM_RESPOSTA:
            return self.resposta
        if not self.dados["solicitacao_id"]:
            self.dados["solicitacao_id"] = "pedido-1"
        if self.dados["solicitacao_estado"] == "atendida" and self.novo_ciclo:   # ponte abre novo UUID após atender
            self.dados["solicitacao_id"], self.dados["solicitacao_estado"] = "pedido-2", ""
        if self.dados["solicitacao_estado"] not in ("enviada", "atendida"):
            self.dados["solicitacao_estado"] = self.entrega
        return self.dados["solicitacao_id"]


class BaseLicencaTelegram(BaseTelegram):
    def setUp(self):
        super().setUp()
        self.publica = ed25519.chave_publica(SEMENTE_TESTE)
        self.tg.chave_publica = self.publica
        self.banco.cfg_set("licenca_exigir", "S")
        self.cliente(CLIENTE_SECRETO)
        self.sem_ponte()                    # cada teste escolhe a ponte; nunca a real
        self.parear()

    def ativar(self, dias=30, emitida=HOJE, hoje=HOJE) -> str:
        codigo = licenca.gerar_licenca(SEMENTE_TESTE, LOJA, dias, emitida)
        licenca.ativar(self.banco, codigo, hoje=hoje, chave_publica=self.publica)
        return codigo

    def usar_ponte(self, ponte):
        anterior = sys.modules.get("src.sync.ponte")
        sys.modules["src.sync.ponte"] = ponte
        self.addCleanup(lambda: sys.modules.__setitem__("src.sync.ponte", anterior) if anterior
                        else sys.modules.pop("src.sync.ponte", None))
        return ponte

    def sem_ponte(self):
        """Simula a instalação sem src.sync.ponte (None em sys.modules faz o import falhar)."""
        self.usar_ponte(None)

    def ir_para(self, dia: date, hora=21):
        self._hora["t"] = datetime(dia.year, dia.month, dia.day, hora, 0, 0)

    def avisos(self) -> list[str]:
        return [r["texto"] for r in self.banco.todos("SELECT texto FROM telegram_fila WHERE tipo = 'licenca' ORDER BY id")]

    def assertSemSegredos(self, texto, codigo=None):
        self.assertNotIn(CLIENTE_SECRETO, texto)
        self.assertNotIn("PDVL1", texto)
        self.assertNotIn(self.banco.cfg("telegram_token"), texto)
        if codigo:
            self.assertNotIn(codigo, texto)


class TesteTecladoEComandos(BaseLicencaTelegram):
    def test_teclado_em_duas_colunas_sem_repetir_e_com_os_botoes_novos(self):
        botoes = [b for linha in TECLADO for b in linha]
        self.assertEqual(botoes, [t for t, _ in BOTOES])
        self.assertEqual(len(botoes), len(set(botoes)))
        self.assertTrue(all(len(linha) == 2 for linha in TECLADO[:-1]))
        self.assertIn(len(TECLADO[-1]), (1, 2) if len(BOTOES) % 2 else (2,))
        for esperado in ("🔐 Licença", "🛟 Suporte", "🔄 Renovar", "❓ Ajuda", "📊 Resumo"):
            self.assertIn(esperado, botoes)

    def test_teclado_impar_deixa_o_ultimo_sozinho(self):
        botoes = [("A", "a"), ("B", "b"), ("C", "c")]
        teclado = [[t for t, _ in botoes[i:i + 2]] for i in range(0, len(botoes), 2)]
        self.assertEqual(teclado, [["A", "B"], ["C"]])

    def test_variacoes_dos_comandos(self):
        for texto in ("🔐 Licença", "licenca", "Licença", "/licenca", "/licenca@casa_bot"):
            self.assertEqual(normalizar_comando(texto), "licenca", texto)
        for texto in ("🛟 Suporte", "suporte", "saude", "saúde", "central", "status"):
            self.assertEqual(normalizar_comando(texto), "suporte", texto)
        for texto in ("🔄 Renovar", "renovar", "/renovar", "renovação"):
            self.assertEqual(normalizar_comando(texto), "renovar", texto)
        self.assertEqual(normalizar_comando("❓ Ajuda"), "ajuda")

    def test_ajuda_organizada_e_sem_operacao_financeira(self):
        r = self.pergunta("❓ Ajuda")
        for secao in ("Vendas", "Operação", "Estoque", "Financeiro", "Licença e suporte"):
            self.assertIn(secao, r)
        self.assertIn("só consulta", r)
        self.assertLess(len(r), 4096)


class TesteConsultaLicenca(BaseLicencaTelegram):
    def test_licenca_em_dia_mostra_validade_sem_o_codigo(self):
        codigo = self.ativar(30)
        r = self.pergunta("🔐 Licença")
        self.assertIn("Em dia", r)
        self.assertIn("Válida até: 02/11/2026", r)
        self.assertIn("Faltam 30 dias", r)
        self.assertSemSegredos(r, codigo)

    def test_licenca_vencendo_em_carencia_e_bloqueada(self):
        codigo = self.ativar(5)
        r = self.pergunta("licenca")
        self.assertIn("Vence em breve", r)
        self.assertIn("vence em 5 dias", r)
        self.ir_para(date(2026, 10, 10))
        self.assertIn("em carência", self.pergunta("licença"))
        self.ir_para(date(2026, 10, 20))
        r = self.pergunta("licença")
        self.assertIn("carência encerrada", r)
        self.assertSemSegredos(r, codigo)

    def test_sem_licenca_e_desativada(self):
        r = self.pergunta("licenca")
        self.assertIn("Sem licença válida", r)
        self.assertIn("Nenhuma licença ativada", r)
        self.banco.cfg_set("licenca_exigir", "")
        r = self.pergunta("licenca")
        self.assertIn("Não exigida", r)
        self.assertNotIn("Renovar", r)

    def test_licenca_mostra_pedido_pendente_da_ponte(self):
        self.ativar(5)
        self.usar_ponte(PonteFalsa(ultimo_sucesso="2026-10-03 20:15:00", solicitacao_id="p-1",
                                   solicitacao_estado="pendente"))
        r = self.pergunta("licenca")
        self.assertIn("Pedido de renovação: registrado neste caixa, aguardando conexão", r)
        self.assertNotIn("p-1", r)
        self.usar_ponte(PonteFalsa(solicitacao_id="p-1", solicitacao_estado="enviada"))
        self.assertIn("Pedido de renovação: entregue ao fornecedor", self.pergunta("licenca"))

    def test_estranho_e_grupo_nao_recebem_licenca(self):
        self.ativar(30)
        self.tg_http.enviadas.clear()
        self.tg_http.digitar(ESTRANHO, "licenca")
        self.tg_http.digitar(DONO, "licenca", tipo="group")
        self.tg_http.digitar(DONO, "licenca", tipo="supergroup")
        self.tg.processar_atualizacoes(0)
        self.assertEqual(self.tg_http.textos(ESTRANHO), ["🔒 Este bot é privado."])
        self.assertEqual(self.tg_http.textos(DONO), [])

    def test_telegram_desligado_nao_responde_licenca(self):
        self.ativar(30)
        self.banco.cfg_set("telegram_ativo", "N")
        self.assertIn("desligado", self.pergunta("licenca"))


class TesteSuporte(BaseLicencaTelegram):
    def test_sem_ponte_informa_que_nao_esta_configurada(self):
        self.sem_ponte()
        self.ativar(30)
        r = self.pergunta("🛟 Suporte")
        self.assertIn("Versão do PDV:", r)
        self.assertIn("ainda não configurado", r)
        self.assertSemSegredos(r)

    def test_mostra_ultimo_contato_erro_generico_e_pendencia(self):
        self.ativar(30)
        self.banco.cfg_set("api_token", "SEGREDO-DO-CAIXA-123")
        self.banco.cfg_set("telegram_erro", "falhou em https://api.telegram.org/bot" + self.banco.cfg("telegram_token"))
        self.usar_ponte(PonteFalsa(ultimo_sucesso="2026-10-02 18:30:00", ultima_tentativa="2026-10-03 20:00:00",
                                   erro="401 token SEGREDO-DO-CAIXA-123 recusado", solicitacao_id="x",
                                   solicitacao_estado="enviada"))
        notificacoes.enfileirar(self.banco, "turno", "aviso parado")
        r = self.pergunta("suporte")
        self.assertIn("Último contato com o fornecedor: 02/10/2026 às 18:30", r)
        self.assertIn("A última tentativa de contato falhou", r)
        self.assertIn("entregue ao fornecedor, aguardando a nova licença", r)
        self.assertNotIn("CX-TESTE", r)
        self.assertIn("Avisos esperando envio: 1", r)
        self.assertIn("O envio de avisos teve erro", r)
        self.assertNotIn("SEGREDO-DO-CAIXA-123", r)
        self.assertNotIn("api.telegram.org", r)
        self.assertSemSegredos(r)

    def test_falha_ao_ler_a_ponte_vira_erro_generico(self):
        self.ativar(30)
        self.usar_ponte(PonteFalsa(falha_estado=RuntimeError("banco travado com token XYZ")))
        with self.assertLogs("pdv.telegram") as logs:
            r = self.pergunta("saude")
        self.assertNotIn("XYZ", "\n".join(logs.output))
        self.assertIn("falhou", r)
        self.assertNotIn("XYZ", r)

    def test_ponte_desligada(self):
        self.ativar(30)
        self.usar_ponte(PonteFalsa(ativa=False, erro="antigo"))
        r = self.pergunta("suporte")
        self.assertIn("Contato com o fornecedor: desligado neste caixa.", r)
        self.assertNotIn("antigo", r)


class TestePedidoDeRenovacao(BaseLicencaTelegram):
    def test_pedido_confirmado_pela_ponte(self):
        self.ativar(5)
        ponte = self.usar_ponte(PonteFalsa())
        r = self.pergunta("🔄 Renovar")
        self.assertEqual(len(ponte.chamadas), 1)
        self.assertIs(ponte.chamadas[0][0], self.banco)
        self.assertIsNone(ponte.chamadas[0][1])
        self.assertIn("Pedido de renovação entregue ao fornecedor", r)
        self.assertNotIn("pedido-1", r)
        self.assertIn("só muda depois que o novo código for aplicado", r)
        self.assertNotIn("renovada", r.lower())
        self.assertSemSegredos(r)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'telegram_renovacao_pedida'"), 1)

    def test_pedido_repetido_nao_cria_outro(self):
        self.ativar(5)
        self.usar_ponte(PonteFalsa(solicitacao_id="pedido-1", solicitacao_estado="enviada"))
        self.assertIn("Já existe um pedido", self.pergunta("renovar"))

    def test_pedido_atendido_aparece_concluido_na_licenca_e_no_suporte(self):
        self.ativar(30)
        self.usar_ponte(PonteFalsa(solicitacao_id="p-9", solicitacao_estado="atendida"))
        for comando in ("licenca", "suporte"):
            r = self.pergunta(comando)
            self.assertIn("Pedido de renovação: concluído, nova licença já aplicada neste caixa", r)
            self.assertNotIn("p-9", r)
            self.assertNotIn("aguardando", r)

    def test_pendente_e_enviada_nao_falam_em_licenca_aplicada(self):
        self.ativar(5)
        for estado in ("pendente", "enviada"):
            with self.subTest(estado=estado):
                self.usar_ponte(PonteFalsa(solicitacao_id="p-1", solicitacao_estado=estado))
                for comando in ("licenca", "suporte", "renovar"):
                    r = self.pergunta(comando).lower()
                    self.assertNotIn("aplicada neste caixa", r)
                    self.assertNotIn("concluído", r)
                    self.assertNotIn("renovada", r)

    def test_apos_atendida_novo_pedido_abre_outro_ciclo(self):
        self.ativar(5)
        ponte = self.usar_ponte(PonteFalsa(solicitacao_id="p-1", solicitacao_estado="atendida"))
        r = self.pergunta("renovar")
        self.assertIn("Pedido de renovação entregue ao fornecedor", r)
        self.assertNotIn("Já existe", r)
        self.assertEqual(ponte.dados["solicitacao_id"], "pedido-2")

    def test_ponte_que_ainda_devolve_o_pedido_atendido_nao_finge_novo_pedido(self):
        self.ativar(5)
        ponte = PonteFalsa(solicitacao_id="p-1", solicitacao_estado="atendida")
        ponte.novo_ciclo = False
        self.usar_ponte(ponte)
        r = self.pergunta("renovar")
        self.assertIn("já foi concluído", r)
        self.assertNotIn("entregue ao fornecedor", r)
        self.assertNotIn("NÃO chegou", r)

    def test_sem_conexao_fica_pendente_sem_sucesso_falso(self):
        self.ativar(5)
        self.usar_ponte(PonteFalsa(entrega="pendente"))
        r = self.pergunta("renovar")
        self.assertIn("ainda NÃO chegou ao fornecedor", r)
        self.assertNotIn("entregue ao fornecedor", r)
        self.assertIn("registrado neste caixa", self.pergunta("licenca"))

    def test_pedido_nao_altera_a_licenca(self):
        codigo = self.ativar(5)
        self.usar_ponte(PonteFalsa())
        self.pergunta("renovar")
        self.assertEqual(self.banco.cfg("licenca_token"), codigo)

    def test_erro_de_negocio_da_ponte_e_mostrado_sem_sucesso_falso(self):
        self.ativar(5)
        self.usar_ponte(PonteFalsa(falha_pedido=ErroNegocio("Este caixa ainda não foi aprovado pelo fornecedor.")))
        r = self.pergunta("renovar")
        self.assertIn("Não foi possível pedir a renovação: Este caixa ainda não foi aprovado", r)
        self.assertNotIn("entregue", r)
        self.assertNotIn("registrado neste caixa", r)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'telegram_renovacao_pedida'"), 0)

    def test_falha_de_rede_e_generica_e_sem_sucesso_falso(self):
        self.ativar(5)
        self.usar_ponte(PonteFalsa(falha_pedido=OSError("conexão recusada em https://ponte?token=ABC")))
        with self.assertLogs("pdv.telegram") as logs:
            r = self.pergunta("renovar")
        self.assertNotIn("ABC", "\n".join(logs.output))
        self.assertIn("Não consegui enviar o pedido", r)
        self.assertNotIn("ABC", r)
        self.assertNotIn("entregue ao fornecedor", r)

    def test_resposta_sem_confirmacao_nao_e_sucesso(self):
        self.ativar(5)
        for resposta in (None, "", "   ", {}, {"status": "enviada"}, True):
            with self.subTest(resposta=resposta):
                self.usar_ponte(PonteFalsa(resposta=resposta, solicitacao_id="velho", solicitacao_estado="enviada"))
                with self.assertLogs("pdv.telegram"):
                    r = self.pergunta("renovar")
                self.assertIn("não foi registrado", r)
                self.assertNotIn("entregue ao fornecedor", r)

    def test_sem_ponte_instalada(self):
        self.ativar(5)
        self.sem_ponte()
        self.assertIn("ainda não está disponível", self.pergunta("renovar"))

    def test_licenca_desativada_nao_chama_a_ponte(self):
        self.banco.cfg_set("licenca_exigir", "")
        ponte = self.usar_ponte(PonteFalsa())
        self.assertIn("não é exigida", self.pergunta("renovar"))
        self.assertEqual(ponte.chamadas, [])

    def test_estranho_e_grupo_nao_pedem_renovacao(self):
        self.ativar(5)
        ponte = self.usar_ponte(PonteFalsa())
        self.tg_http.digitar(ESTRANHO, "renovar")
        self.tg_http.digitar(DONO, "renovar", tipo="group")
        self.tg.processar_atualizacoes(0)
        self.assertEqual(ponte.chamadas, [])

    def test_telegram_desligado_nao_pede_renovacao(self):
        self.ativar(5)
        ponte = self.usar_ponte(PonteFalsa())
        self.banco.cfg_set("telegram_ativo", "N")
        self.pergunta("renovar")
        self.assertEqual(ponte.chamadas, [])


class TesteAvisosDeLicenca(BaseLicencaTelegram):
    def test_aviso_de_vencimento_uma_vez_por_dia_mesmo_reiniciando(self):
        self.ativar(5)
        self.assertTrue(self.tg.aviso_licenca())
        self.assertFalse(self.tg.aviso_licenca())
        reiniciado = TelegramController(self.banco, self.tg_http)
        reiniciado.chave_publica = self.publica
        self.assertFalse(reiniciado.aviso_licenca())
        self.assertEqual(len(self.avisos()), 1)
        self.assertIn("vence em 5 dias", self.avisos()[0])
        self.assertIn("Renovar", self.avisos()[0])
        self.avancar(hours=1)
        self.assertFalse(self.tg.aviso_licenca())
        self.ir_para(date(2026, 10, 4))
        self.assertTrue(self.tg.aviso_licenca())
        self.assertEqual(len(self.avisos()), 2)
        self.assertIn("vence em 4 dias", self.avisos()[1])

    def test_aviso_vai_para_a_fila_e_sai_so_para_os_pareados(self):
        self.ativar(5)
        self.tg.aviso_licenca()
        self.tg.processar_fila()
        self.assertEqual(len(self.tg_http.textos(DONO)), 1)
        self.assertEqual(self.tg_http.textos(ESTRANHO), [])
        self.assertSemSegredos(self.tg_http.textos(DONO)[0])

    def test_licenca_em_dia_nao_avisa(self):
        self.ativar(30)
        self.assertFalse(self.tg.aviso_licenca())
        self.assertEqual(self.avisos(), [])
        self.assertTrue(self.banco.cfg(CHAVE_AVISO_LICENCA))   # guarda a validade para reconhecer a renovação

    def test_carencia_e_bloqueio_avisam(self):
        self.ativar(2)
        self.ir_para(date(2026, 10, 7))
        self.assertTrue(self.tg.aviso_licenca())
        self.assertIn("venceu em 05/10/2026", self.avisos()[-1])
        self.ir_para(date(2026, 10, 20))
        self.assertTrue(self.tg.aviso_licenca())
        self.assertIn("carência terminou", self.avisos()[-1])

    def test_sem_licenca_avisa_e_desativada_nao(self):
        self.assertTrue(self.tg.aviso_licenca())
        self.assertIn("Nenhuma licença ativada", self.avisos()[-1])
        self.banco.cfg_set("licenca_exigir", "")
        self.ir_para(date(2026, 10, 4))
        self.assertFalse(self.tg.aviso_licenca())
        self.assertEqual(len(self.avisos()), 1)

    def test_renovacao_aplicada_e_anunciada_uma_vez(self):
        self.ativar(5)
        self.tg.aviso_licenca()
        self.avancar(hours=1)
        self.ativar(40)                                           # novo código aplicado neste caixa
        self.assertTrue(self.tg.aviso_licenca())
        self.assertIn("renovada e aplicada neste caixa: válida até 12/11/2026", self.avisos()[-1])
        self.assertFalse(self.tg.aviso_licenca())
        self.ir_para(date(2026, 10, 5))
        self.assertFalse(self.tg.aviso_licenca())
        self.assertEqual(len(self.avisos()), 2)

    def test_pedido_de_renovacao_nao_anuncia_renovacao(self):
        self.ativar(5)
        self.tg.aviso_licenca()
        self.usar_ponte(PonteFalsa())
        self.pergunta("renovar")
        self.avancar(hours=1)
        self.assertFalse(self.tg.aviso_licenca())
        self.assertFalse(any("renovada" in t for t in self.avisos()))

    def test_telegram_desligado_ou_sem_pareado_nao_avisa_nem_marca(self):
        self.ativar(5)
        self.banco.cfg_set("telegram_ativo", "N")
        self.assertFalse(self.tg.aviso_licenca())
        self.banco.cfg_set("telegram_ativo", "S")
        self.banco.executar("DELETE FROM telegram_chats")
        self.assertFalse(self.tg.aviso_licenca())
        self.assertEqual(self.avisos(), [])
        self.assertEqual(self.banco.cfg(CHAVE_AVISO_LICENCA), "")

    def test_marca_e_aviso_na_mesma_transacao(self):
        self.ativar(5)
        original = self.banco.cfg_set

        def quebra(chave, valor):
            if chave == CHAVE_AVISO_LICENCA:
                raise RuntimeError("disco cheio")
            return original(chave, valor)

        self.banco.cfg_set = quebra
        with self.assertLogs("pdv.telegram"):
            self.assertFalse(self.tg.aviso_licenca())
        self.banco.cfg_set = original
        self.assertEqual(self.avisos(), [])                        # desfez o aviso junto com a marca
        self.assertTrue(self.tg.aviso_licenca())                   # e tenta de novo depois
        self.assertEqual(len(self.avisos()), 1)