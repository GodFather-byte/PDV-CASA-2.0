"""Hotel (Will Hotel): tarifas viram produtos, reservas sem conflito, check-in com a ficha, conta na comanda, diárias,
período com hora adicional, check-out, governança, mapa, relatórios e fichas dos hóspedes."""
from __future__ import annotations

import csv
import tempfile
from datetime import datetime
from pathlib import Path

from src.controllers.caixa_controller import CaixaController
from src.controllers.hotel_controller import HotelController, cpf_valido, idade
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.base import BaseTeste

CPF_MARIA = "529.982.247-25"
CPF_CARLOS = "111.444.777-35"


class BaseHotel(BaseTeste):
    agora = datetime(2026, 11, 23, 15, 0, 0)       # segunda-feira, depois do check-in das 14:00

    def setUp(self):
        super().setUp()
        from src.controllers.perfil_controller import PerfilController
        PerfilController(self.banco).aplicar("hotel")
        for chave, valor in (("usar_hotel", "S"), ("limite_comanda", "0"), ("num_comandas", "999")):
            self.banco.cfg_set(chave, valor)
        self.op = self.operador_adm()
        self.h = HotelController(self.banco, self.op)
        self.standard = self.h.salvar_tipo("Standard casal", 2, 15000, cafe_incluso=True)
        self.familia = self.h.salvar_tipo("Família", 4, 25000, cafe_incluso=False)
        self.q101 = self.h.salvar_uh("101", self.standard)
        self.q102 = self.h.salvar_uh("102", self.standard)
        self.q201 = self.h.salvar_uh("201", self.familia, andar="2º")
        self.duas_horas = self.h.salvar_periodo("2 horas", 120, 6000)
        self.h.definir_preco_extra("cafe", 2500)
        self.h.definir_preco_extra("hora_extra", 3000)
        self.maria = self.h.salvar_hospede({"nome": "Maria da Silva", "cpf": CPF_MARIA, "documento": "12.345.678-9",
                                            "nascimento": "10/05/1985", "telefone": "(11) 98888-7777",
                                            "cidade": "Campinas", "uf": "sp"})
        self.carlos = self.h.salvar_hospede({"nome": "Carlos Souza", "cpf": CPF_CARLOS, "nascimento": "02/02/1990"})

    def abrir_caixa(self):
        TurnoController(self.banco).abrir(self.op, 1, 0)

    def hospedar(self, uh=None, saida="2026-11-26", hospede=None, **kw):
        if TurnoController(self.banco).atual() is None:
            self.abrir_caixa()
        hospede = hospede or self.maria
        estadia = self.h.reservar(uh or self.q101, "Maria da Silva", "2026-11-23", saida, hospede_id=hospede, **kw)
        return self.h.checkin(estadia, hospede)["id"]

    def conta(self, estadia_id):
        e = self.h.estadia(estadia_id)
        return self.banco.um("SELECT * FROM vendas WHERE id = ?", (e["venda_id"],))

    def itens(self, estadia_id):
        e = self.h.estadia(estadia_id)
        return [(r["nome"], r["quantidade"], r["total_cent"]) for r in self.banco.todos(
            """SELECT p.nome, i.quantidade, i.total_cent FROM itens_venda i JOIN produtos p ON p.id = i.produto_id
               WHERE i.venda_id = ? AND i.cancelado = 0 ORDER BY i.id""", (e["venda_id"],))]


class TesteCadastro(BaseHotel):
    def test_tipo_de_quarto_cria_a_diaria_como_produto_sem_servico(self):
        tipo = next(t for t in self.h.tipos() if t["id"] == self.standard)
        produto = self.banco.um("SELECT * FROM produtos WHERE id = ?", (tipo["produto_diaria_id"],))
        self.assertEqual((produto["nome"], produto["preco_cent"], produto["cobrar_servico"]),
                         ("DIÁRIA STANDARD CASAL", 15000, 0))
        self.assertEqual(self.banco.valor("""SELECT g.nome FROM subgrupos s JOIN grupos g ON g.id = s.grupo_id
                                             WHERE s.id = ?""", (produto["subgrupo_id"],)), "HOSPEDAGEM")
        self.h.salvar_tipo("Standard casal", 2, 16000, tipo_id=self.standard)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (produto["id"],)), 16000)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos WHERE nome LIKE 'DIÁRIA%'"), 2)
        self.assertEqual(tipo["uhs"], 2)

    def test_cadastros_recusam_repetido_e_valor_invalido(self):
        with self.assertRaises(ErroNegocio):
            self.h.salvar_tipo("standard CASAL", 2, 10000)
        with self.assertRaises(ErroValidacao):
            self.h.salvar_tipo("Suíte", 2, 0)
        with self.assertRaises(ErroValidacao):
            self.h.salvar_tipo("Suíte", 30, 10000)
        with self.assertRaises(ErroNegocio):
            self.h.salvar_uh("101", self.standard)
        with self.assertRaises(ErroValidacao):
            self.h.salvar_periodo("Rapidinho", 10, 1000)

    def test_quartos_saem_em_ordem_numerica(self):
        self.h.salvar_uh("12", self.standard)
        self.h.salvar_uh("3", self.standard)
        self.assertEqual([u["numero"] for u in self.h.uhs()], ["3", "12", "101", "102", "201"])

    def test_manutencao_pede_o_motivo_e_tira_o_quarto_da_venda(self):
        with self.assertRaises(ErroValidacao):
            self.h.marcar_limpeza(self.q102, "manutencao")
        self.h.marcar_limpeza(self.q102, "manutencao", "ar-condicionado quebrado")
        self.assertEqual(self.h.uh(self.q102)["motivo_manutencao"], "ar-condicionado quebrado")
        livres = [u["numero"] for u in self.h.disponiveis("2026-11-23 14:00", "2026-11-24 12:00")]
        self.assertEqual(livres, ["101", "201"])

    def test_quarto_com_reserva_nao_e_desativado(self):
        self.h.reservar(self.q101, "Fulano de Tal", "2026-11-25", "2026-11-26")
        with self.assertRaises(ErroNegocio):
            self.h.desativar_uh(self.q101)
        self.h.desativar_uh(self.q102)
        self.assertNotIn("102", [u["numero"] for u in self.h.uhs()])


class TesteHospedes(BaseHotel):
    def test_cpf_e_data_de_nascimento(self):
        self.assertTrue(cpf_valido(CPF_MARIA))
        self.assertFalse(cpf_valido("111.111.111-11"))
        self.assertFalse(cpf_valido("529.982.247-24"))
        self.assertEqual(idade("1985-05-10"), 41)
        h = self.h.hospede(self.maria)
        self.assertEqual((h["cpf"], h["nascimento"], h["uf"]), ("52998224725", "1985-05-10", "SP"))

    def test_recusa_dados_errados_e_cpf_repetido(self):
        for dados in ({"nome": "Jo"}, {"nome": "Ana Lima", "cpf": "123"}, {"nome": "Ana Lima", "email": "ana@"},
                      {"nome": "Ana Lima", "nascimento": "31/02/2000"}, {"nome": "Ana Lima", "uf": "XX"},
                      {"nome": "Ana Lima", "cpf": CPF_MARIA}):
            with self.subTest(dados=dados), self.assertRaises(ErroValidacao):
                self.h.salvar_hospede(dados)
        self.h.salvar_hospede({"nome": "Maria da Silva Souza", "cpf": CPF_MARIA}, self.maria)     # o próprio cadastro

    def test_busca_por_nome_cpf_e_telefone(self):
        self.assertEqual([h["id"] for h in self.h.buscar_hospedes("maria")], [self.maria])
        self.assertEqual([h["id"] for h in self.h.buscar_hospedes("529982")], [self.maria])
        self.assertEqual([h["id"] for h in self.h.buscar_hospedes("98888-7777")], [self.maria])
        self.assertEqual(len(self.h.buscar_hospedes("")), 2)


class TesteReservas(BaseHotel):
    def test_reserva_por_noites_nos_horarios_do_hotel(self):
        r = self.h.reservar(self.q101, "Maria da Silva", "25/11/2026", "28/11/2026", telefone="11 98888-7777",
                            origem="whatsapp")
        e = self.h.estadia(r)
        self.assertEqual((e["entrada_prevista"], e["saida_prevista"], e["noites"], e["situacao"]),
                         ("2026-11-25 14:00:00", "2026-11-28 12:00:00", 3, "reservada"))
        self.assertEqual((e["cafe_incluso"], e["preco_cent"], e["origem_rotulo"]), (1, 15000, "WhatsApp"))

    def test_conflito_no_mesmo_quarto_e_saida_no_dia_da_entrada_do_outro(self):
        self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-28")
        with self.assertRaisesRegex(ErroNegocio, "já está com Maria da Silva de 25/11/2026 a 28/11/2026"):
            self.h.reservar(self.q101, "Carlos Souza", "2026-11-27", "2026-11-29")
        self.h.reservar(self.q101, "Carlos Souza", "2026-11-28", "2026-11-30")          # sai às 12h, o outro entra às 14h
        self.h.reservar(self.q101, "Ana Lima", "2026-11-23", "2026-11-25")

    def test_periodo_choca_com_a_diaria_do_mesmo_dia(self):
        self.h.reservar(self.q101, "Maria da Silva", "2026-11-24", "2026-11-25")
        with self.assertRaises(ErroNegocio):
            self.h.reservar(self.q101, "Casal", "2026-11-24 13:00", modalidade="periodo", periodo_id=self.duas_horas)
        self.h.reservar(self.q101, "Casal", "2026-11-24 11:00", modalidade="periodo", periodo_id=self.duas_horas)

    def test_capacidade_data_passada_e_limite_de_noites(self):
        with self.assertRaisesRegex(ErroNegocio, "até 2 pessoas"):
            self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-26", adultos=2, criancas=1)
        with self.assertRaises(ErroValidacao):
            self.h.reservar(self.q101, "Maria da Silva", "2026-11-20", "2026-11-26")
        with self.assertRaises(ErroValidacao):
            self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-25")
        with self.assertRaises(ErroValidacao):
            self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2027-06-25")

    def test_cancelar_e_nao_compareceu_liberam_o_quarto(self):
        r = self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-28")
        with self.assertRaises(ErroValidacao):
            self.h.cancelar(r, "")
        with self.assertRaises(ErroNegocio):
            self.h.nao_compareceu(r)                                  # ainda não chegou o dia
        self.h.cancelar(r, "desistiu da viagem")
        self.assertEqual(self.h.estadia(r)["situacao"], "cancelada")
        self.h.reservar(self.q101, "Carlos Souza", "2026-11-25", "2026-11-28")
        hoje = self.h.reservar(self.q102, "Ana Lima", "2026-11-23", "2026-11-24")
        self.h.nao_compareceu(hoje)
        self.assertEqual(self.h.estadia(hoje)["situacao"], "nao_compareceu")

    def test_mudar_datas_da_reserva_confere_o_quarto(self):
        r = self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-27")
        self.h.reservar(self.q101, "Carlos Souza", "2026-11-28", "2026-11-30")
        with self.assertRaises(ErroNegocio):
            self.h.alterar_datas(r, "2026-11-25", "2026-11-29")
        self.h.alterar_datas(r, "2026-11-24", "2026-11-28")
        self.assertEqual(self.h.estadia(r)["noites"], 4)

    def test_trocar_quarto_da_reserva(self):
        r = self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-27")
        self.h.reservar(self.q102, "Carlos Souza", "2026-11-26", "2026-11-28")
        with self.assertRaises(ErroNegocio):
            self.h.trocar_quarto(r, self.q102)
        self.h.trocar_quarto(r, self.q201)
        self.assertEqual(self.h.estadia(r)["uh"], "201")

    def test_sem_modulo_ligado_nao_reserva(self):
        self.banco.cfg_set("usar_hotel", "N")
        with self.assertRaisesRegex(ErroNegocio, "desligado"):
            self.h.reservar(self.q101, "Maria da Silva", "2026-11-25", "2026-11-26")


class TesteCheckin(BaseHotel):
    def setUp(self):
        super().setUp()
        self.abrir_caixa()

    def test_checkin_abre_a_conta_numa_comanda_com_o_nome_do_quarto(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-26")
        e = self.h.checkin(r, self.maria, motivo_viagem="Lazer ou férias", meio_transporte="Automóvel",
                           procedencia="Campinas/SP")
        conta = self.conta(r)
        self.assertEqual((e["situacao"], e["conta"], e["titular_nome"]), ("hospedada", 500, "Maria da Silva"))
        self.assertEqual((conta["modalidade"], conta["comanda"], conta["posicao"], conta["apelido"]),
                         ("mesa", 1, 500, "Q101 Maria da Silva"))
        outro = self.h.reservar(self.q102, "Carlos", "2026-11-23", "2026-11-24", hospede_id=self.carlos)
        self.assertEqual(self.h.checkin(outro)["conta"], 501)

    def test_checkin_exige_ficha_completa_e_responsavel_do_menor(self):
        r = self.h.reservar(self.q201, "Maria", "2026-11-23", "2026-11-25", adultos=1, criancas=1)
        sem_doc = self.h.salvar_hospede({"nome": "Pedro Alves"})
        with self.assertRaisesRegex(ErroValidacao, "falta documento, data de nascimento"):
            self.h.checkin(r, sem_doc)
        with self.assertRaisesRegex(ErroValidacao, "Cadastre o hóspede"):
            self.h.checkin(r)
        menor = self.h.salvar_hospede({"nome": "Joao da Silva", "documento": "99.999.999-9", "nascimento": "01/01/2015"})
        with self.assertRaisesRegex(ErroValidacao, "menor de idade"):
            self.h.checkin(r, self.maria, [{"hospede_id": menor}])
        with self.assertRaisesRegex(ErroNegocio, "maior de idade"):
            self.h.checkin(r, menor)
        e = self.h.checkin(r, self.maria, [{"hospede_id": menor, "responsavel": "mãe, Maria da Silva"}])
        self.assertEqual([(a["nome"], a["responsavel"]) for a in e["acompanhantes"]],
                         [("Joao da Silva", "mãe, Maria da Silva")])

    def test_adulto_brasileiro_sem_cpf_nao_entra(self):
        sem_cpf = self.h.salvar_hospede({"nome": "Pedro Alves", "documento": "1234567", "nascimento": "1980-01-01"})
        estrangeiro = self.h.salvar_hospede({"nome": "John Smith", "documento_tipo": "Passaporte", "documento": "X123",
                                             "nascimento": "1980-01-01", "nacionalidade": "Americana", "pais": "EUA"})
        r = self.h.reservar(self.q101, "Pedro", "2026-11-23", "2026-11-24")
        with self.assertRaisesRegex(ErroValidacao, "falta CPF"):
            self.h.checkin(r, sem_cpf)
        self.assertEqual(self.h.checkin(r, estrangeiro)["situacao"], "hospedada")

    def test_quarto_sujo_so_com_confirmacao_e_em_manutencao_nunca(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria)
        self.h.marcar_limpeza(self.q101, "sujo")
        with self.assertRaisesRegex(ErroNegocio, "está sujo"):
            self.h.checkin(r)
        self.h.marcar_limpeza(self.q101, "manutencao", "vazamento")
        with self.assertRaisesRegex(ErroNegocio, "manutenção"):
            self.h.checkin(r, permitir_quarto_sujo=True)
        self.h.marcar_limpeza(self.q101, "sujo")
        self.assertEqual(self.h.checkin(r, permitir_quarto_sujo=True)["situacao"], "hospedada")

    def test_reserva_de_outro_dia_nao_faz_checkin(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-25", "2026-11-26", hospede_id=self.maria)
        with self.assertRaisesRegex(ErroNegocio, "25/11/2026"):
            self.h.checkin(r)

    def test_checkin_direto_sem_reserva(self):
        e = self.h.checkin_direto(self.q102, self.carlos, "2026-11-24", meio_transporte="Ônibus")
        self.assertEqual((e["situacao"], e["uh"], e["noites"], e["meio_transporte"]), ("hospedada", "102", 1, "Ônibus"))

    def test_checkin_precisa_do_caixa_aberto(self):
        TurnoController(self.banco).fechar(TurnoController(self.banco).atual()["id"], self.op, 0,
                                           justificativa="teste")
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria)
        with self.assertRaises(ErroNegocio):
            self.h.checkin(r)
        self.assertEqual(self.h.estadia(r)["situacao"], "reservada")          # nada ficou pela metade


class TesteContaECheckout(BaseHotel):
    def test_diarias_vencidas_cafe_e_checkout_no_horario(self):
        r = self.hospedar(saida="2026-11-26")
        self.avancar(days=2, hours=-6)                                    # 25/11 09:00
        self.assertEqual(self.h.lancar_diarias(r), 2)
        self.assertEqual(self.h.lancar_diarias(r), 0)                       # não repete
        self.h.lancar_cafe(r, 1)
        self.avancar(days=1, hours=2)                                    # 26/11 11:00
        previa = self.h.previa_checkout(r)
        self.assertEqual((previa["atraso_min"], previa["a_lancar_cent"]), (0, 15000))
        saida = self.h.checkout(r)
        self.assertEqual(self.itens(r), [("DIÁRIA STANDARD CASAL", 2, 30000), ("CAFÉ DA MANHÃ AVULSO", 1, 2500),
                                         ("DIÁRIA STANDARD CASAL", 1, 15000)])
        self.assertEqual((saida["conta"], saida["total_cent"]), (500, 47500))
        e = self.h.estadia(r)
        self.assertEqual((e["situacao"], e["diarias_lancadas"], e["limpeza"]), ("encerrada", 3, "sujo"))

    def test_atraso_no_checkout_avisa_e_cobra_a_diaria_extra_so_se_pedir(self):
        r = self.hospedar(saida="2026-11-24")
        self.avancar(days=1, minutes=-120)                               # 24/11 13:00, uma hora depois das 12:00
        previa = self.h.previa_checkout(r)
        self.assertEqual((previa["atraso_min"], previa["linhas"][0]["quantidade"]), (60, 1))
        self.assertEqual(self.h.previa_checkout(r, cobrar_diaria_extra=True)["linhas"][0]["quantidade"], 2)
        self.h.checkout(r, cobrar_diaria_extra=True)
        self.assertEqual(self.itens(r), [("DIÁRIA STANDARD CASAL", 2, 30000)])

    def test_saida_no_mesmo_dia_cobra_uma_diaria(self):
        r = self.hospedar(saida="2026-11-24")
        self.avancar(hours=3)
        self.h.checkout(r)
        self.assertEqual(self.itens(r), [("DIÁRIA STANDARD CASAL", 1, 15000)])

    def test_conta_paga_no_caixa_com_adiantamento(self):
        r = self.hospedar(saida="2026-11-24")
        caixa = CaixaController(self.banco, self.op)
        venda = self.h.estadia(r)["venda_id"]
        caixa.adicionar_pagamento(venda, self.tipo("Dinheiro"), 10000)       # pagou adiantado no check-in
        self.avancar(hours=20)
        self.assertEqual(self.h.previa_checkout(r)["saldo_cent"], 5000)
        saida = self.h.checkout(r)
        caixa.adicionar_pagamento(venda, self.tipo("Dinheiro"), saida["total_cent"] - saida["pago_cent"])
        caixa.fechar(venda)
        self.assertEqual(self.conta(r)["status"], "fechada")
        self.assertFalse(self.h.estadia(r)["conta_aberta"])

    def test_conta_fechada_no_caixa_antes_da_saida_nao_recebe_mais_lancamento(self):
        r = self.hospedar(saida="2026-11-24")
        caixa = CaixaController(self.banco, self.op)
        venda = self.h.estadia(r)["venda_id"]
        caixa.adicionar_item(venda, self.novo_produto("AGUA", 500), 1)
        caixa.adicionar_pagamento(venda, self.tipo("Dinheiro"), 500)
        caixa.fechar(venda)
        with self.assertRaisesRegex(ErroNegocio, "já foi fechada"):
            self.h.lancar_cafe(r, 1)

    def test_periodo_com_hora_adicional_depois_da_tolerancia(self):
        self.abrir_caixa()
        r = self.h.reservar(self.q102, "Carlos", "2026-11-23 15:00", modalidade="periodo",
                            periodo_id=self.duas_horas, hospede_id=self.carlos)
        self.avancar(minutes=10)
        e = self.h.checkin(r)
        self.assertEqual(e["saida_prevista"], "2026-11-23 17:10:00")          # conta da entrada de verdade
        self.avancar(hours=2, minutes=10)                                 # 10 min depois: dentro da tolerância
        self.assertEqual(len(self.h.previa_checkout(r)["linhas"]), 1)
        self.avancar(minutes=70)                                          # 1h20 depois do fim
        painel = self.h.painel_hoje()
        self.assertEqual((painel["periodos"][0]["alerta"], painel["periodos"][0]["relogio"]), ("estourou", "1:20:00"))
        self.h.checkout(r)
        self.assertEqual(self.itens(r), [("PERÍODO 2 HORAS", 1, 6000), ("HORA ADICIONAL", 2, 6000)])

    def test_prorrogar_e_trocar_de_quarto_hospedado(self):
        r = self.hospedar(saida="2026-11-24")
        self.h.alterar_datas(r, saida="2026-11-27")
        self.assertEqual(self.h.estadia(r)["saida_prevista"], "2026-11-27 12:00:00")
        self.h.trocar_quarto(r, self.q102)
        self.assertEqual((self.h.uh(self.q101)["limpeza"], self.conta(r)["apelido"]), ("sujo", "Q102 Maria da Silva"))
        self.assertEqual(self.h.lancar_diarias(r, ate="2026-11-26"), 3)          # cobrou adiantado até o dia 26
        with self.assertRaisesRegex(ErroNegocio, "mais diárias lançadas"):
            self.h.alterar_datas(r, saida="2026-11-25")
        self.avancar(days=2)
        with self.assertRaisesRegex(ErroValidacao, "já passou"):
            self.h.alterar_datas(r, saida="2026-11-24")

    def test_auditoria_da_noite_lanca_todas_as_diarias(self):
        a = self.hospedar(self.q101, saida="2026-11-27")
        b = self.hospedar(self.q102, saida="2026-11-27", hospede=self.carlos)
        self.avancar(days=2)
        self.assertEqual(self.h.lancar_diarias_vencidas(), 4)
        self.assertEqual((self.h.estadia(a)["diarias_lancadas"], self.h.estadia(b)["diarias_lancadas"]), (2, 2))


class TestePaineisERelatorios(BaseHotel):
    def test_painel_do_dia(self):
        self.hospedar(self.q101, saida="2026-11-24")
        self.h.reservar(self.q102, "Carlos", "2026-11-23", "2026-11-25")
        self.h.reservar(self.q201, "Ana Lima", "2026-11-25", "2026-11-26")
        self.h.marcar_limpeza(self.q201, "sujo")
        resumo = self.h.painel_hoje()["resumo"]
        self.assertEqual({k: resumo[k] for k in ("quartos", "ocupados", "livres", "prontos", "sujos", "chegadas", "saidas")},
                         {"quartos": 3, "ocupados": 1, "livres": 2, "prontos": 1, "sujos": 1, "chegadas": 1, "saidas": 0})
        self.avancar(days=1)
        self.assertEqual(self.h.painel_hoje()["resumo"]["saidas"], 1)

    def test_mapa_em_blocos_por_noite(self):
        self.hospedar(self.q101, saida="2026-11-25")
        self.h.reservar(self.q101, "Carlos", "2026-11-25", "2026-11-28")
        self.h.reservar(self.q201, "Ana Lima", "2026-12-01", "2026-12-10")
        mapa = self.h.mapa("2026-11-22", 14)
        self.assertEqual(len(mapa["datas"]), 14)
        linha = next(l for l in mapa["linhas"] if l["uh"]["numero"] == "101")
        self.assertEqual([(b["titular"], b["col_ini"], b["col_fim"], b["situacao"]) for b in linha["blocos"]],
                         [("Maria da Silva", 1, 3, "hospedada"), ("Carlos", 3, 6, "reservada")])
        longo = next(l for l in mapa["linhas"] if l["uh"]["numero"] == "201")["blocos"][0]
        self.assertEqual((longo["col_ini"], longo["col_fim"], longo["continua_depois"]), (9, 14, True))

    def test_ocupacao_diaria_media_e_revpar(self):
        r = self.hospedar(self.q101, saida="2026-11-25")
        self.avancar(days=2, hours=-4)
        self.h.checkout(r)
        rel = self.h.ocupacao("2026-11-23", "2026-11-25")       # a receita conta no dia do lançamento (o check-out)
        self.assertEqual((rel["noites_disponiveis"], rel["noites_vendidas"], rel["ocupacao_pct"]), (9, 2, 22.2))
        self.assertEqual((rel["receita_diarias_cent"], rel["diaria_media_cent"], rel["revpar_cent"]), (30000, 15000, 3333))
        self.assertEqual([d["ocupados"] for d in rel["por_dia"]], [1, 1, 0])
        with self.assertRaises(ErroValidacao):
            self.h.ocupacao("2026-11-24", "2026-11-23")

    def test_cafe_do_dia_separa_incluso_de_avulso(self):
        self.hospedar(self.q101, saida="2026-11-25")
        self.hospedar(self.q201, saida="2026-11-25", hospede=self.carlos, adultos=2)
        self.assertEqual(self.h.cafe_do_dia("2026-11-23")["pessoas"], 0)          # ninguém dormiu ainda
        cafe = self.h.cafe_do_dia("2026-11-24")
        self.assertEqual((cafe["pessoas"], cafe["inclusos"], cafe["avulsos"]), (3, 1, 2))
        self.assertEqual([q["uh"] for q in cafe["quartos"]], ["101", "201"])

    def test_fichas_dos_hospedes_para_a_fnrh(self):
        self.abrir_caixa()
        menor = self.h.salvar_hospede({"nome": "Joao da Silva", "documento": "99.999.999-9", "nascimento": "01/01/2015"})
        r = self.h.reservar(self.q201, "Maria", "2026-11-23", "2026-11-25", hospede_id=self.maria, criancas=1)
        self.h.checkin(r, self.maria, [{"hospede_id": menor, "responsavel": "mãe"}], motivo_viagem="Lazer ou férias")
        self.h.reservar(self.q101, "Reserva futura", "2026-11-26", "2026-11-27")      # sem check-in: fora
        fichas = self.h.fichas("2026-11-01", "2026-11-30")
        self.assertEqual([(f["nome"], f["titular"], f["responsavel"], f["cpf"]) for f in fichas],
                         [("Maria da Silva", "Sim", "", CPF_MARIA), ("Joao da Silva", "Não", "mãe", "")])
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self.h.exportar_fichas("2026-11-01", "2026-11-30", Path(pasta) / "fichas.csv")
            with caminho.open(encoding="utf-8-sig") as arquivo:
                linhas = list(csv.reader(arquivo, delimiter=";"))
        self.assertEqual(linhas[0][:4], ["Entrada", "Saída", "Quarto", "Nome"])
        self.assertEqual(linhas[1][3], "Maria da Silva")
        self.assertEqual(len(linhas), 3)


class TestePerfilEEdicao(BaseTeste):
    def test_perfil_hotel_tira_servico_e_cria_as_categorias(self):
        from src.controllers.perfil_controller import PerfilController
        PerfilController(self.banco).aplicar("hotel")
        self.assertEqual((self.banco.cfg("cobra_servico_comanda"), self.banco.cfg("usar_garotas"),
                          self.banco.cfg("usar_portaria")), ("N", "N", "N"))
        self.assertIn("HOSPEDAGEM", [r[0] for r in self.banco.todos("SELECT nome FROM grupos")])

    def test_edicao_will_hotel_liga_o_hotel_e_esconde_a_boate(self):
        import os
        from unittest import mock
        from src.core import edicao
        with mock.patch.dict(os.environ, {edicao.VARIAVEL: "willhotel"}):
            ed = edicao.atual()
            edicao.preparar(self.banco)
        self.assertEqual((ed.nome, ed.executavel, ed.script_instalador), ("Will Hotel", "WillHotel", "WillHotel.iss"))
        for chave, valor in (("usar_hotel", "S"), ("usar_garotas", "N"), ("usar_quartos", "N"), ("limite_comanda", "0"),
                             ("num_comandas", "999"), ("tempo_inatividade_min", "0"), ("edicao", "willhotel")):
            self.assertEqual(self.banco.cfg(chave), valor, chave)
        self.assertIn("limite_comanda", ed.fora_das_configuracoes())
        self.assertNotIn("hotel", ed.menu_oculto)
        for outra in ("willpdv", "willadega", "willrestaurante"):
            self.assertIn("hotel", edicao.EDICOES[outra].menu_oculto)
            self.assertIn("usar_hotel", edicao.EDICOES[outra].fora_das_configuracoes())

    def test_configuracoes_do_hotel_validam_horario_e_limites(self):
        from src.controllers.config_controller import ConfigController
        config = ConfigController(self.banco)
        config.salvar_config({"hotel_checkin_hora": "15", "hotel_checkout_hora": "11:30"})
        self.assertEqual((self.banco.cfg("hotel_checkin_hora"), self.banco.cfg("hotel_checkout_hora")),
                         ("15:00", "11:30"))
        for chave, valor in (("hotel_checkin_hora", "25:00"), ("hotel_tolerancia_min", "999"),
                             ("hotel_conta_inicio", "0")):
            with self.subTest(chave=chave), self.assertRaises(ErroValidacao):
                config.salvar_config({chave: valor})

    def test_modulo_hotel_esconde_os_acessos_quando_desligado(self):
        from src.controllers.config_controller import modulos_desligados
        self.assertTrue({"util_hotel", "cfg_hotel"} <= modulos_desligados(self.banco))
        self.banco.cfg_set("usar_hotel", "S")
        self.assertFalse({"util_hotel", "cfg_hotel"} & modulos_desligados(self.banco))
