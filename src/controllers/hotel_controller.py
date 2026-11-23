"""Hotel (edição Will Hotel): quartos, reservas, check-in, conta da estadia, check-out, governança e relatórios.

Duas formas de vender o quarto:

* **Diária** (reserva por noites): entra no horário do check-in (padrão 14:00) e sai no do check-out (padrão 12:00) do
  último dia. A diária é o produto do tipo de quarto; o número de diárias é o de noites, no mínimo uma.
* **Período** (uso por horas): 2 h, 4 h, pernoite... O período é um produto; passou do tempo além da tolerância, cada
  hora começada vira uma "hora adicional".

A conta da estadia é uma **comanda do caixa** aberta no check-in, numerada a partir de `hotel_conta_inicio` (padrão 500):
o que se consome (café da manhã avulso, extras) cai nela pelo próprio caixa, e o pagamento, inclusive adiantado, é o do
caixa. Diárias e horas são lançadas por aqui (`lancar_diarias`, `checkout`). Dinheiro é sempre centavos inteiros.

A ficha do hóspede guarda os dados da Ficha Nacional de Registro de Hóspedes (FNRH Digital), que o hotel envia ao
Ministério do Turismo pelo site do governo; o sistema não envia nada, só organiza e exporta (`fichas`, `exportar_fichas`).
Esses dados ficam só no computador da loja: nada daqui sobe para a nuvem.
"""
from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao

ATIVAS = ("reservada", "hospedada")
SITUACOES = {"reservada": "Reservada", "hospedada": "Hospedada", "encerrada": "Encerrada", "cancelada": "Cancelada",
             "nao_compareceu": "Não compareceu"}
LIMPEZA = {"limpo": "Limpo", "sujo": "Sujo", "arrumando": "Arrumando", "manutencao": "Manutenção"}
ORIGENS = {"balcao": "Balcão", "telefone": "Telefone", "whatsapp": "WhatsApp", "site": "Site", "agencia": "Agência",
           "empresa": "Empresa (convênio)", "outro": "Outro"}
DOCUMENTOS = ("RG", "CNH", "Passaporte", "RNE/CRNM", "Certidão de nascimento", "Outro")
GENEROS = ("Feminino", "Masculino", "Outro", "Prefiro não informar")
MOTIVOS_VIAGEM = ("Lazer ou férias", "Negócios ou trabalho", "Congresso, feira ou evento", "Visita a parentes ou amigos",
                  "Estudos ou cursos", "Saúde", "Religião", "Compras", "Outro")
MEIOS_TRANSPORTE = ("Automóvel", "Ônibus", "Avião", "Moto", "Navio ou barco", "Trem", "Outro")
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ",
       "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")
MAX_NOITES = 90
MAX_DIAS_MAPA = 62
GRUPO_PRODUTOS = "HOSPEDAGEM"
SUBGRUPO_DIARIAS = "DIÁRIAS E PERÍODOS"
SUBGRUPO_SERVICOS = "SERVIÇOS DO HOTEL"


def _dt(iso: str) -> datetime:
    return datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")


def _iso(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M:%S")


def _data(texto) -> date:
    """'2026-11-23', '23/11/2026' ou um date -> date."""
    if isinstance(texto, datetime):
        return texto.date()
    if isinstance(texto, date):
        return texto
    try:
        iso = fmt.para_data_iso(texto)
    except ValueError as erro:
        raise ErroValidacao(str(erro).capitalize() + ".") from None
    if iso is None:
        raise ErroValidacao("Informe a data.")
    return datetime.strptime(iso, "%Y-%m-%d").date()


def _momento(texto) -> datetime:
    """'2026-11-23 15:30:00', '23/11/2026 15:30' ou um datetime -> datetime (sem segundos fracionados)."""
    if isinstance(texto, datetime):
        return texto.replace(microsecond=0)
    s = " ".join(str(texto or "").split())
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, formato)
        except ValueError:
            continue
    raise ErroValidacao(f"Data e hora inválidas: {texto!r} (use dd/mm/aaaa hh:mm).")


def cpf_valido(cpf: str) -> bool:
    numeros = re.sub(r"\D", "", cpf or "")
    if len(numeros) != 11 or numeros == numeros[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(numeros[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(numeros[tamanho]):
            return False
    return True


def fmt_cpf(cpf: str | None) -> str:
    n = re.sub(r"\D", "", cpf or "")
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}" if len(n) == 11 else (cpf or "")


def idade(nascimento: str | None, em: date | None = None) -> int | None:
    if not nascimento:
        return None
    nasc = datetime.strptime(nascimento[:10], "%Y-%m-%d").date()
    hoje = em or fmt.agora_dt().date()
    return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))


def fmt_duracao(minutos: int) -> str:
    h, m = divmod(int(minutos), 60)
    if h and m:
        return f"{h}h{m:02d}"
    return f"{h}h" if h else f"{m} min"


def fmt_relogio(segundos: float) -> str:
    s = int(abs(segundos))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class HotelController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    # ============================================================ configuração
    def ligado(self) -> bool:
        return self.banco.cfg_bool("usar_hotel", False)

    def _exigir_ligado(self) -> None:
        if not self.ligado():
            raise ErroNegocio("O módulo Hotel está desligado (Configurações > Módulos).")

    def config(self) -> dict:
        b = self.banco
        return {
            "checkin": fmt.para_hora(b.cfg("hotel_checkin_hora", "14:00") or "14:00"),
            "checkout": fmt.para_hora(b.cfg("hotel_checkout_hora", "12:00") or "12:00"),
            "conta_inicio": max(1, b.cfg_int("hotel_conta_inicio", 500)),
            "tolerancia_min": max(0, b.cfg_int("hotel_tolerancia_min", 15)),
            "alerta_min": max(0, b.cfg_int("hotel_alerta_min", 15)),
        }

    def _caixa(self):
        from src.controllers.caixa_controller import CaixaController
        return CaixaController(self.banco, self.operador_id)

    # ============================================================ produtos
    def _produtos(self):
        from src.controllers.produto_controller import ProdutoController
        return ProdutoController(self.banco)

    def _subgrupo(self, nome: str) -> int:
        """O subgrupo do hotel dentro do grupo HOSPEDAGEM (cria os dois se faltarem)."""
        grupo = self.banco.valor("SELECT id FROM grupos WHERE UPPER(nome) = ?", (GRUPO_PRODUTOS,))
        if grupo is None:
            grupo = self.banco.inserir("grupos", {"nome": GRUPO_PRODUTOS})
        sub = self.banco.valor("SELECT id FROM subgrupos WHERE grupo_id = ? AND UPPER(nome) = ?", (grupo, nome.upper()))
        if sub is None:
            sub = self.banco.inserir("subgrupos", {"grupo_id": grupo, "nome": nome})
        return sub

    def _salvar_produto(self, produto_id: int | None, nome: str, preco_cent: int, subgrupo: str) -> int:
        """Cria ou atualiza o produto que o caixa cobra (diária, período, café, hora adicional). O nome segue o do hotel;
        preço zero não vende."""
        from src.controllers.cadastro_controller import CadastroController
        if preco_cent <= 0:
            raise ErroValidacao("Informe o preço (maior que zero).", {"preco": "inválido"})
        produtos = self._produtos()
        atual = produtos.por_id(produto_id) if produto_id else None
        nome = " ".join(nome.upper().split())[:60]
        outro = self.banco.valor("SELECT id FROM produtos WHERE nome = ?", (nome,))
        if outro and (atual is None or outro != atual["id"]):
            raise ErroNegocio(f"Já existe um produto chamado {nome}. Use outro nome.")
        dados = {"nome": nome, "preco_cent": fmt.fmt_num(preco_cent), "cobrar_servico": "N",
                 "mostrar_no_cardapio": "N", "subgrupo_id": self._subgrupo(subgrupo)}
        if atual is None:
            dados.update({"codigo": produtos.proximo_codigo(),
                          "unidade_id": self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
                          or self.banco.valor("SELECT id FROM unidades ORDER BY id LIMIT 1")})
            return CadastroController(self.banco).salvar("produtos", dados)
        dados["codigo"] = atual["codigo"]
        dados["unidade_id"] = atual["unidade_id"]
        CadastroController(self.banco).salvar("produtos", dados, atual["id"])
        return atual["id"]

    def _preco(self, produto_id: int | None) -> int:
        if not produto_id:
            return 0
        return self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ? AND ativo = 1", (produto_id,), 0) or 0

    EXTRAS = {"cafe": ("hotel_produto_cafe", "CAFÉ DA MANHÃ AVULSO"),
              "hora_extra": ("hotel_produto_hora_extra", "HORA ADICIONAL")}

    def precos_extras(self) -> dict:
        return {chave: self._preco(self.banco.cfg_int(cfg, 0)) for chave, (cfg, _) in self.EXTRAS.items()}

    def definir_preco_extra(self, chave: str, preco_cent: int) -> int:
        """Café da manhã avulso (por pessoa) ou hora adicional do período."""
        if chave not in self.EXTRAS:
            raise ErroValidacao("Serviço desconhecido.")
        cfg, nome = self.EXTRAS[chave]
        with self.banco.transacao():
            pid = self._salvar_produto(self.banco.cfg_int(cfg, 0) or None, nome, preco_cent, SUBGRUPO_SERVICOS)
            self.banco.cfg_set(cfg, pid)
        self.banco.log("hotel_preco", f"{nome}: {fmt.fmt_brl(preco_cent)}", self.operador_id)
        return pid

    # ============================================================ tipos de quarto
    def tipos(self, ativos: bool = True) -> list[dict]:
        linhas = [dict(r) for r in self.banco.todos(
            "SELECT * FROM hotel_tipos" + (" WHERE ativo = 1" if ativos else "") + " ORDER BY nome")]
        for t in linhas:
            t["preco_diaria_cent"] = self._preco(t["produto_diaria_id"])
            t["uhs"] = self.banco.valor("SELECT COUNT(*) FROM hotel_uhs WHERE tipo_id = ? AND ativo = 1", (t["id"],), 0)
        return linhas

    def salvar_tipo(self, nome: str, capacidade: int, preco_diaria_cent: int, cafe_incluso: bool = True,
                    descricao: str | None = None, tipo_id: int | None = None) -> int:
        nome = " ".join((nome or "").split())
        if not nome:
            raise ErroValidacao("Dê um nome ao tipo de quarto (ex.: Standard casal).", {"nome": "obrigatório"})
        if len(nome) > 40:
            raise ErroValidacao("O nome do tipo vai até 40 letras.", {"nome": "inválido"})
        if not 1 <= int(capacidade) <= 20:
            raise ErroValidacao("A capacidade vai de 1 a 20 pessoas.", {"capacidade": "inválido"})
        atual = self.banco.um("SELECT * FROM hotel_tipos WHERE id = ?", (tipo_id,)) if tipo_id else None
        if tipo_id and atual is None:
            raise ErroNegocio("Tipo de quarto não encontrado.")
        repetido = self.banco.valor("SELECT id FROM hotel_tipos WHERE UPPER(nome) = UPPER(?)", (nome,))
        if repetido and repetido != tipo_id:
            raise ErroNegocio(f"Já existe o tipo {nome}.")
        with self.banco.transacao():
            produto = self._salvar_produto(atual["produto_diaria_id"] if atual else None, f"DIÁRIA {nome}",
                                           int(preco_diaria_cent), SUBGRUPO_DIARIAS)
            dados = {"nome": nome, "capacidade": int(capacidade), "produto_diaria_id": produto,
                     "cafe_incluso": int(bool(cafe_incluso)), "descricao": (descricao or "").strip() or None, "ativo": 1}
            if atual:
                self.banco.atualizar("hotel_tipos", tipo_id, dados)
            else:
                tipo_id = self.banco.inserir("hotel_tipos", dados)
        self.banco.log("hotel_tipo", f"{nome}: diária {fmt.fmt_brl(preco_diaria_cent)}", self.operador_id)
        return tipo_id

    # ============================================================ quartos (UH)
    def uhs(self, ativas: bool = True) -> list[dict]:
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT u.*, t.nome AS tipo, t.capacidade, t.produto_diaria_id, t.cafe_incluso
               FROM hotel_uhs u JOIN hotel_tipos t ON t.id = u.tipo_id"""
            + (" WHERE u.ativo = 1" if ativas else "") + " ORDER BY u.ordem, u.numero")]
        for u in linhas:
            u["limpeza_rotulo"] = LIMPEZA[u["limpeza"]]
        return self._ordenar_uhs(linhas)

    @staticmethod
    def _ordenar_uhs(linhas: list[dict]) -> list[dict]:
        def chave(u):
            numero = str(u["numero"])
            return (u.get("ordem", 0), int(numero) if numero.isdigit() else 10**9, numero)
        return sorted(linhas, key=chave)

    def uh(self, uh_id: int) -> dict:
        r = self.banco.um("""SELECT u.*, t.nome AS tipo, t.capacidade, t.produto_diaria_id, t.cafe_incluso
                             FROM hotel_uhs u JOIN hotel_tipos t ON t.id = u.tipo_id WHERE u.id = ?""", (uh_id,))
        if r is None:
            raise ErroNegocio("Quarto não encontrado.")
        u = dict(r)
        u["limpeza_rotulo"] = LIMPEZA[u["limpeza"]]
        return u

    def salvar_uh(self, numero: str, tipo_id: int, andar: str | None = None, observacao: str | None = None,
                  uh_id: int | None = None, ordem: int = 0) -> int:
        numero = " ".join(str(numero or "").split()).upper()
        if not numero or len(numero) > 10:
            raise ErroValidacao("Informe o número do quarto (até 10 letras ou números).", {"numero": "inválido"})
        if self.banco.um("SELECT 1 FROM hotel_tipos WHERE id = ? AND ativo = 1", (tipo_id,)) is None:
            raise ErroValidacao("Escolha o tipo do quarto.", {"tipo_id": "obrigatório"})
        repetido = self.banco.valor("SELECT id FROM hotel_uhs WHERE numero = ?", (numero,))
        if repetido and repetido != uh_id:
            raise ErroNegocio(f"Já existe o quarto {numero}.")
        dados = {"numero": numero, "tipo_id": int(tipo_id), "andar": (andar or "").strip() or None,
                 "observacao": (observacao or "").strip() or None, "ordem": int(ordem or 0), "ativo": 1}
        with self.banco.transacao():
            if uh_id:
                self.uh(uh_id)
                self.banco.atualizar("hotel_uhs", uh_id, dados)
            else:
                uh_id = self.banco.inserir("hotel_uhs", dados)
        self.banco.log("hotel_uh", f"quarto {numero}", self.operador_id)
        return uh_id

    def desativar_uh(self, uh_id: int) -> None:
        u = self.uh(uh_id)
        ativa = self.banco.valor(
            f"SELECT COUNT(*) FROM hotel_estadias WHERE uh_id = ? AND situacao IN {ATIVAS}", (uh_id,), 0)
        if ativa:
            raise ErroNegocio(f"O quarto {u['numero']} tem reserva ou hóspede. Mude a estadia de quarto antes.")
        self.banco.executar("UPDATE hotel_uhs SET ativo = 0 WHERE id = ?", (uh_id,))
        self.banco.log("hotel_uh_desativado", f"quarto {u['numero']}", self.operador_id)

    def marcar_limpeza(self, uh_id: int, situacao: str, motivo: str | None = None) -> None:
        """Governança: limpo, sujo, arrumando ou manutenção (manutenção pede o motivo e tira o quarto da venda)."""
        if situacao not in LIMPEZA:
            raise ErroValidacao("Situação de arrumação inválida.")
        u = self.uh(uh_id)
        motivo = " ".join((motivo or "").split()) or None
        if situacao == "manutencao" and not motivo:
            raise ErroValidacao("Diga o que o quarto tem (ex.: ar-condicionado quebrado).", {"motivo": "obrigatório"})
        self.banco.executar("UPDATE hotel_uhs SET limpeza = ?, motivo_manutencao = ? WHERE id = ?",
                            (situacao, motivo if situacao == "manutencao" else None, uh_id))
        self.banco.log("hotel_limpeza", f"quarto {u['numero']}: {LIMPEZA[situacao]}", self.operador_id)

    # ============================================================ períodos
    def periodos(self, ativos: bool = True) -> list[dict]:
        linhas = [dict(r) for r in self.banco.todos(
            "SELECT * FROM hotel_periodos" + (" WHERE ativo = 1" if ativos else "") + " ORDER BY minutos")]
        for p in linhas:
            p["preco_cent"] = self._preco(p["produto_id"])
            p["duracao"] = fmt_duracao(p["minutos"])
        return linhas

    def salvar_periodo(self, nome: str, minutos: int, preco_cent: int, periodo_id: int | None = None) -> int:
        nome = " ".join((nome or "").split())
        if not nome or len(nome) > 30:
            raise ErroValidacao("Dê um nome ao período (ex.: 2 horas, Pernoite).", {"nome": "inválido"})
        if not 30 <= int(minutos) <= 1440:
            raise ErroValidacao("O período vai de 30 minutos a 24 horas.", {"minutos": "inválido"})
        atual = self.banco.um("SELECT * FROM hotel_periodos WHERE id = ?", (periodo_id,)) if periodo_id else None
        if periodo_id and atual is None:
            raise ErroNegocio("Período não encontrado.")
        repetido = self.banco.valor("SELECT id FROM hotel_periodos WHERE UPPER(nome) = UPPER(?)", (nome,))
        if repetido and repetido != periodo_id:
            raise ErroNegocio(f"Já existe o período {nome}.")
        with self.banco.transacao():
            produto = self._salvar_produto(atual["produto_id"] if atual else None, f"PERÍODO {nome}", int(preco_cent),
                                           SUBGRUPO_DIARIAS)
            dados = {"nome": nome, "minutos": int(minutos), "produto_id": produto, "ativo": 1}
            if atual:
                self.banco.atualizar("hotel_periodos", periodo_id, dados)
            else:
                periodo_id = self.banco.inserir("hotel_periodos", dados)
        self.banco.log("hotel_periodo", f"{nome}: {fmt_duracao(minutos)} {fmt.fmt_brl(preco_cent)}", self.operador_id)
        return periodo_id

    def desativar_periodo(self, periodo_id: int) -> None:
        self.banco.executar("UPDATE hotel_periodos SET ativo = 0 WHERE id = ?", (periodo_id,))

    def desativar_tipo(self, tipo_id: int) -> None:
        if self.banco.valor("SELECT COUNT(*) FROM hotel_uhs WHERE tipo_id = ? AND ativo = 1", (tipo_id,), 0):
            raise ErroNegocio("Há quartos deste tipo. Troque o tipo deles ou desative os quartos antes.")
        self.banco.executar("UPDATE hotel_tipos SET ativo = 0 WHERE id = ?", (tipo_id,))

    # ============================================================ hóspedes
    CAMPOS_HOSPEDE = ("nome", "cpf", "documento_tipo", "documento", "documento_emissor", "nascimento", "genero",
                      "nacionalidade", "telefone", "email", "profissao", "cidade", "uf", "pais", "observacao")

    def salvar_hospede(self, dados: dict, hospede_id: int | None = None) -> int:
        """Cadastro do hóspede com os campos da ficha (FNRH). Só o nome é obrigatório aqui; o check-in exige documento
        e data de nascimento."""
        d = {c: " ".join(str(dados.get(c) or "").split()) or None for c in self.CAMPOS_HOSPEDE}
        erros = {}
        if not d["nome"] or len(d["nome"]) < 3:
            erros["nome"] = "Informe o nome completo."
        elif len(d["nome"]) > 80:
            erros["nome"] = "O nome vai até 80 letras."
        if d["cpf"]:
            if not cpf_valido(d["cpf"]):
                erros["cpf"] = "CPF inválido."
            else:
                d["cpf"] = re.sub(r"\D", "", d["cpf"])
                outro = self.banco.valor("SELECT id FROM hotel_hospedes WHERE cpf = ?", (d["cpf"],))
                if outro and outro != hospede_id:
                    erros["cpf"] = "Já há um hóspede com este CPF. Procure pelo CPF e use o cadastro dele."
        d["documento_tipo"] = d["documento_tipo"] or "RG"
        if d["documento_tipo"] not in DOCUMENTOS:
            erros["documento_tipo"] = "Tipo de documento inválido."
        if d["nascimento"]:
            try:
                d["nascimento"] = fmt.para_data_iso(d["nascimento"])
                anos = idade(d["nascimento"])
                if anos is None or not 0 <= anos <= 120:
                    erros["nascimento"] = "Data de nascimento fora do possível."
            except ValueError:
                erros["nascimento"] = "Data de nascimento inválida (dd/mm/aaaa)."
        if d["genero"] and d["genero"] not in GENEROS:
            erros["genero"] = "Gênero inválido."
        if d["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", d["email"]):
            erros["email"] = "E-mail inválido."
        if d["uf"]:
            d["uf"] = d["uf"].upper()
            if (d["pais"] or "Brasil").lower() == "brasil" and d["uf"] not in UFS:
                erros["uf"] = "UF inválida."
        d["nacionalidade"] = d["nacionalidade"] or "Brasileira"
        d["pais"] = d["pais"] or "Brasil"
        if d["telefone"]:
            numeros = re.sub(r"\D", "", d["telefone"])
            if not 8 <= len(numeros) <= 15:
                erros["telefone"] = "Telefone inválido."
        if erros:
            raise ErroValidacao(next(iter(erros.values())), erros)
        agora = fmt.agora()
        with self.banco.transacao():
            if hospede_id:
                if self.banco.um("SELECT 1 FROM hotel_hospedes WHERE id = ?", (hospede_id,)) is None:
                    raise ErroNegocio("Hóspede não encontrado.")
                self.banco.atualizar("hotel_hospedes", hospede_id, {**d, "atualizado_em": agora})
            else:
                hospede_id = self.banco.inserir("hotel_hospedes", {**d, "criado_em": agora, "atualizado_em": agora})
        return hospede_id

    def hospede(self, hospede_id: int) -> dict:
        r = self.banco.um("SELECT * FROM hotel_hospedes WHERE id = ?", (hospede_id,))
        if r is None:
            raise ErroNegocio("Hóspede não encontrado.")
        h = dict(r)
        h["idade"] = idade(h["nascimento"])
        h["estadias"] = self.banco.valor(
            "SELECT COUNT(*) FROM hotel_estadias WHERE hospede_id = ? AND situacao IN ('hospedada','encerrada')",
            (hospede_id,), 0)
        return h

    def buscar_hospedes(self, texto: str = "", limite: int = 60) -> list[dict]:
        """Pelo nome, CPF, documento ou telefone. Vazio: os atualizados por último."""
        texto = " ".join((texto or "").split())
        numeros = re.sub(r"\D", "", texto)
        if not texto:
            linhas = self.banco.todos("SELECT * FROM hotel_hospedes ORDER BY atualizado_em DESC LIMIT ?", (limite,))
        else:
            parecido = f"%{texto}%"
            linhas = self.banco.todos(
                """SELECT * FROM hotel_hospedes WHERE nome LIKE ? OR documento LIKE ? OR (? <> '' AND
                   (cpf LIKE ? OR REPLACE(REPLACE(REPLACE(telefone,'(',''),')',''),'-','') LIKE ?))
                   ORDER BY nome LIMIT ?""",
                (parecido, parecido, numeros, f"%{numeros}%", f"%{numeros}%", limite))
        return [{**dict(r), "idade": idade(r["nascimento"])} for r in linhas]

    @staticmethod
    def _faltas_ficha(h: dict) -> list[str]:
        """O que falta no cadastro para a ficha do hóspede (FNRH): documento e nascimento; brasileiro adulto, o CPF."""
        faltas = []
        if not h.get("documento") and not h.get("cpf"):
            faltas.append("documento")
        if not h.get("nascimento"):
            faltas.append("data de nascimento")
        anos = idade(h.get("nascimento"))
        if (h.get("nacionalidade") or "Brasileira").lower().startswith("brasil") and anos is not None and anos >= 18 \
                and not h.get("cpf"):
            faltas.append("CPF")
        return faltas

    # ============================================================ estadias: consulta
    def estadia(self, estadia_id: int) -> dict:
        r = self.banco.um(
            """SELECT e.*, u.numero AS uh, u.limpeza, t.nome AS tipo, t.capacidade, p.nome AS periodo,
                      pr.nome AS tarifa
               FROM hotel_estadias e JOIN hotel_uhs u ON u.id = e.uh_id JOIN hotel_tipos t ON t.id = u.tipo_id
               LEFT JOIN hotel_periodos p ON p.id = e.periodo_id LEFT JOIN produtos pr ON pr.id = e.produto_id
               WHERE e.id = ?""", (estadia_id,))
        if r is None:
            raise ErroNegocio("Estadia não encontrada.")
        e = dict(r)
        e["situacao_rotulo"] = SITUACOES[e["situacao"]]
        e["origem_rotulo"] = ORIGENS.get(e["origem"], e["origem"])
        e["noites"] = self._noites_previstas(e)
        e["preco_cent"] = self._preco(e["produto_id"])
        e["acompanhantes"] = [dict(a) for a in self.banco.todos(
            """SELECT h.*, a.responsavel FROM hotel_estadia_hospedes a JOIN hotel_hospedes h ON h.id = a.hospede_id
               WHERE a.estadia_id = ? ORDER BY h.nome""", (estadia_id,))]
        e["conta_aberta"] = bool(e["venda_id"] and self.banco.valor(
            "SELECT 1 FROM vendas WHERE id = ? AND status IN ('aberta','conta_enviada')", (e["venda_id"],)))
        return e

    def _noites_previstas(self, e: dict) -> int:
        if e["modalidade"] != "diaria":
            return 0
        entrada = _dt(e["entrada_em"] or e["entrada_prevista"]).date()
        return max(1, (_dt(e["saida_prevista"]).date() - entrada).days)

    def estadias(self, situacoes: tuple[str, ...] | None = None, texto: str = "", de: str | None = None,
                 ate: str | None = None, limite: int = 300) -> list[dict]:
        """Lista para a aba Reservas: filtro por situação, nome/telefone/quarto e período (pela data de entrada)."""
        filtros, params = [], []
        if situacoes:
            filtros.append(f"e.situacao IN ({','.join('?' * len(situacoes))})")
            params.extend(situacoes)
        texto = " ".join((texto or "").split())
        if texto:
            filtros.append("(e.titular_nome LIKE ? OR e.telefone LIKE ? OR u.numero = ?)")
            params.extend([f"%{texto}%", f"%{texto}%", texto.upper()])
        if de:
            filtros.append("COALESCE(e.entrada_em, e.entrada_prevista) >= ?")
            params.append(f"{_data(de).isoformat()} 00:00:00")
        if ate:
            filtros.append("COALESCE(e.entrada_em, e.entrada_prevista) < ?")
            params.append(f"{(_data(ate) + timedelta(days=1)).isoformat()} 00:00:00")
        where = " WHERE " + " AND ".join(filtros) if filtros else ""
        params.append(limite)
        linhas = [dict(r) for r in self.banco.todos(
            f"""SELECT e.*, u.numero AS uh, t.nome AS tipo, p.nome AS periodo FROM hotel_estadias e
                JOIN hotel_uhs u ON u.id = e.uh_id JOIN hotel_tipos t ON t.id = u.tipo_id
                LEFT JOIN hotel_periodos p ON p.id = e.periodo_id{where}
                ORDER BY COALESCE(e.entrada_em, e.entrada_prevista) DESC, e.id DESC LIMIT ?""", tuple(params))]
        for e in linhas:
            e["situacao_rotulo"] = SITUACOES[e["situacao"]]
            e["noites"] = self._noites_previstas(e)
        return linhas

    # ============================================================ disponibilidade
    def _intervalo(self, e: dict, agora: datetime | None = None) -> tuple[datetime, datetime]:
        """O tempo em que a estadia ocupa o quarto. Hospedado que passou da saída continua ocupando até sair."""
        inicio = _dt(e["entrada_em"] or e["entrada_prevista"])
        fim = _dt(e["saida_prevista"])
        if e["situacao"] == "hospedada":
            fim = max(fim, agora or fmt.agora_dt())
        return inicio, fim

    def conflitos(self, uh_id: int, inicio: datetime, fim: datetime, ignorar: int | None = None) -> list[dict]:
        agora = fmt.agora_dt()
        saida = []
        for r in self.banco.todos(
                f"SELECT * FROM hotel_estadias WHERE uh_id = ? AND situacao IN {ATIVAS} AND id IS NOT ?",
                (uh_id, ignorar)):
            ini, ate = self._intervalo(dict(r), agora)
            if ini < fim and inicio < ate:
                saida.append(dict(r))
        return saida

    def _exigir_livre(self, uh: dict, inicio: datetime, fim: datetime, ignorar: int | None = None) -> None:
        if not uh["ativo"]:
            raise ErroNegocio(f"O quarto {uh['numero']} está desativado.")
        choque = self.conflitos(uh["id"], inicio, fim, ignorar)
        if choque:
            c = choque[0]
            quando = (f"de {fmt.fmt_data(c['entrada_prevista'])} a {fmt.fmt_data(c['saida_prevista'])}"
                      if c["modalidade"] == "diaria" else
                      f"das {fmt.fmt_hora(c['entrada_em'] or c['entrada_prevista'])[:5]} "
                      f"às {fmt.fmt_hora(c['saida_prevista'])[:5]}")
            raise ErroNegocio(f"O quarto {uh['numero']} já está com {c['titular_nome']} {quando}.")

    def disponiveis(self, inicio, fim, pessoas: int = 1) -> list[dict]:
        """Quartos livres no intervalo, que cabem `pessoas`; os em manutenção ficam de fora."""
        ini, ate = _momento(inicio), _momento(fim)
        return [u for u in self.uhs() if u["limpeza"] != "manutencao" and u["capacidade"] >= pessoas
                and not self.conflitos(u["id"], ini, ate)]

    def _datas_diaria(self, entrada, saida) -> tuple[datetime, datetime]:
        c = self.config()
        d_ent, d_sai = _data(entrada), _data(saida)
        noites = (d_sai - d_ent).days
        if noites < 1:
            raise ErroValidacao("A saída tem de ser pelo menos um dia depois da entrada.", {"saida": "inválido"})
        if noites > MAX_NOITES:
            raise ErroValidacao(f"Uma reserva vai até {MAX_NOITES} diárias.", {"saida": "inválido"})
        h_ent = datetime.strptime(c["checkin"], "%H:%M").time()
        h_sai = datetime.strptime(c["checkout"], "%H:%M").time()
        return datetime.combine(d_ent, h_ent), datetime.combine(d_sai, h_sai)

    # ============================================================ estadias: operação
    def reservar(self, uh_id: int, titular_nome: str, entrada, saida=None, *, modalidade: str = "diaria",
                 periodo_id: int | None = None, adultos: int = 1, criancas: int = 0, hospede_id: int | None = None,
                 telefone: str | None = None, cafe_incluso: bool | None = None, origem: str = "balcao",
                 observacao: str | None = None) -> int:
        """Reserva (ou o começo de um check-in direto). Diária: `entrada` e `saida` são datas. Período: `entrada` é a hora
        de chegada e o fim sai da duração do período."""
        self._exigir_ligado()
        uh = self.uh(uh_id)
        titular_nome = " ".join((titular_nome or "").split())
        if hospede_id:
            titular_nome = titular_nome or self.hospede(hospede_id)["nome"]
        if len(titular_nome) < 3:
            raise ErroValidacao("Informe o nome de quem reserva.", {"titular_nome": "obrigatório"})
        if origem not in ORIGENS:
            raise ErroValidacao("Origem da reserva inválida.")
        adultos, criancas = int(adultos), int(criancas)
        if not 1 <= adultos <= 20 or not 0 <= criancas <= 20:
            raise ErroValidacao("Confira o número de adultos e crianças.", {"adultos": "inválido"})
        if adultos + criancas > uh["capacidade"]:
            raise ErroNegocio(f"O quarto {uh['numero']} ({uh['tipo']}) é para até {uh['capacidade']} pessoas.")
        minutos = 0
        if modalidade == "diaria":
            inicio, fim = self._datas_diaria(entrada, saida)
            produto = uh["produto_diaria_id"]
            cafe = uh["cafe_incluso"] if cafe_incluso is None else int(bool(cafe_incluso))
            periodo_id = None
        elif modalidade == "periodo":
            periodo = self.banco.um("SELECT * FROM hotel_periodos WHERE id = ? AND ativo = 1", (periodo_id,))
            if periodo is None:
                raise ErroValidacao("Escolha o período.", {"periodo_id": "obrigatório"})
            inicio = _momento(entrada)
            minutos = periodo["minutos"]
            fim = inicio + timedelta(minutes=minutos)
            produto = periodo["produto_id"]
            cafe = 0
        else:
            raise ErroValidacao("Modalidade inválida.")
        if not self._preco(produto):
            raise ErroNegocio("A tarifa desta estadia está sem preço. Ajuste em Quartos e tarifas.")
        if inicio.date() < fmt.agora_dt().date():
            raise ErroValidacao("A entrada não pode ser num dia que já passou.", {"entrada": "inválido"})
        agora = fmt.agora()
        with self.banco.transacao():
            self._exigir_livre(uh, inicio, fim)
            estadia_id = self.banco.inserir("hotel_estadias", {
                "uuid": str(uuid4()), "uh_id": uh_id, "modalidade": modalidade, "situacao": "reservada",
                "titular_nome": titular_nome, "hospede_id": hospede_id,
                "telefone": " ".join((telefone or "").split()) or None, "adultos": adultos, "criancas": criancas,
                "entrada_prevista": _iso(inicio), "saida_prevista": _iso(fim), "produto_id": produto,
                "periodo_id": periodo_id, "minutos": minutos, "cafe_incluso": cafe, "origem": origem,
                "observacao": (observacao or "").strip() or None, "operador_id": self.operador_id,
                "criado_em": agora, "atualizado_em": agora})
        self.banco.log("hotel_reserva", f"quarto {uh['numero']}: {titular_nome} {_iso(inicio)}", self.operador_id)
        return estadia_id

    def _proxima_conta(self) -> int:
        inicio = self.config()["conta_inicio"]
        maximo = self.banco.cfg_int("num_comandas", 999)
        ocupadas = {r[0] for r in self.banco.todos(
            "SELECT posicao FROM vendas WHERE modalidade = 'mesa' AND comanda = 1 AND status IN ('aberta','conta_enviada')")}
        for numero in range(inicio, maximo + 1):
            if numero not in ocupadas:
                return numero
        raise ErroNegocio(f"Não há número de conta livre de {inicio} a {maximo}. Aumente o número de comandas em "
                          "Configurações.")

    def _abrir_conta(self, e: dict) -> tuple[int, int]:
        caixa = self._caixa()
        numero = self._proxima_conta()
        venda_id, _ = caixa.abrir_mesa(numero, comanda=True)
        caixa.definir_apelido(venda_id, f"Q{e['uh']} {e['titular_nome']}"[:caixa.APELIDO_MAXIMO])
        return venda_id, numero

    def checkin(self, estadia_id: int, hospede_id: int | None = None, acompanhantes: list[dict] | tuple = (), *,
                motivo_viagem: str | None = None, meio_transporte: str | None = None, procedencia: str | None = None,
                proximo_destino: str | None = None, permitir_quarto_sujo: bool = False) -> dict:
        """Entrada do hóspede: confere a ficha, ocupa o quarto e abre a conta (comanda) no caixa.
        `acompanhantes`: [{"hospede_id": 3, "responsavel": "mãe, Maria"}]; menor de 18 sem o titular como responsável
        pede o nome do responsável."""
        self._exigir_ligado()
        e = self.estadia(estadia_id)
        if e["situacao"] != "reservada":
            raise ErroNegocio(f"Esta estadia está {e['situacao_rotulo'].lower()}: o check-in é de reserva.")
        agora = fmt.agora_dt()
        if e["modalidade"] == "diaria" and _dt(e["entrada_prevista"]).date() > agora.date():
            raise ErroNegocio(f"A reserva é para {fmt.fmt_data(e['entrada_prevista'])}. Mude a data antes do check-in.")
        hospede_id = hospede_id or e["hospede_id"]
        if not hospede_id:
            raise ErroValidacao("Cadastre o hóspede titular (com documento) para o check-in.", {"hospede_id": "obrigatório"})
        titular = self.hospede(hospede_id)
        faltas = self._faltas_ficha(titular)
        if faltas:
            raise ErroValidacao(f"Complete a ficha de {titular['nome']}: falta {', '.join(faltas)}.",
                                {"hospede_id": "incompleto"})
        if titular["idade"] is not None and titular["idade"] < 18:
            raise ErroNegocio("O titular da hospedagem tem de ser maior de idade.")
        vistos = {hospede_id}
        lista = []
        for a in acompanhantes or ():
            hid = int(a["hospede_id"])
            if hid in vistos:
                continue
            vistos.add(hid)
            h = self.hospede(hid)
            faltas = [f for f in self._faltas_ficha(h) if f != "CPF" or (h["idade"] or 0) >= 18]
            if faltas:
                raise ErroValidacao(f"Complete a ficha de {h['nome']}: falta {', '.join(faltas)}.")
            responsavel = " ".join(str(a.get("responsavel") or "").split()) or None
            if h["idade"] is not None and h["idade"] < 18 and not responsavel:
                raise ErroValidacao(f"{h['nome']} é menor de idade: informe o responsável e o parentesco.",
                                    {"responsavel": "obrigatório"})
            lista.append((hid, responsavel))
        if 1 + len(lista) > e["capacidade"]:
            raise ErroNegocio(f"O quarto {e['uh']} é para até {e['capacidade']} pessoas.")
        if e["limpeza"] == "manutencao":
            raise ErroNegocio(f"O quarto {e['uh']} está em manutenção. Mude a estadia de quarto.")
        if e["limpeza"] != "limpo" and not permitir_quarto_sujo:
            raise ErroNegocio(f"O quarto {e['uh']} está {LIMPEZA[e['limpeza']].lower()}. Confirme com a arrumação antes.")
        for campo, valor, opcoes in (("motivo", motivo_viagem, MOTIVOS_VIAGEM), ("transporte", meio_transporte,
                                                                                    MEIOS_TRANSPORTE)):
            if valor and valor not in opcoes:
                raise ErroValidacao(f"Escolha o {campo} da viagem na lista.")
        dados = {"situacao": "hospedada", "hospede_id": hospede_id, "titular_nome": titular["nome"],
                 "entrada_em": _iso(agora), "motivo_viagem": motivo_viagem or None,
                 "meio_transporte": meio_transporte or None,
                 "procedencia": " ".join((procedencia or "").split()) or None,
                 "proximo_destino": " ".join((proximo_destino or "").split()) or None,
                 "adultos": max(e["adultos"], 1 + sum(1 for hid, _ in lista
                                                       if (self.hospede(hid)["idade"] or 18) >= 18)),
                 "telefone": e["telefone"] or titular["telefone"], "atualizado_em": _iso(agora)}
        if e["modalidade"] == "periodo":
            dados["saida_prevista"] = _iso(agora + timedelta(minutes=e["minutos"]))
            inicio, fim = agora, agora + timedelta(minutes=e["minutos"])
        else:
            inicio, fim = agora, _dt(e["saida_prevista"])
        with self.banco.transacao():
            self._exigir_livre(self.uh(e["uh_id"]), inicio, fim, ignorar=estadia_id)
            venda_id, conta = self._abrir_conta({**e, "titular_nome": titular["nome"]})
            dados.update({"venda_id": venda_id, "conta": conta})
            self.banco.atualizar("hotel_estadias", estadia_id, dados)
            self.banco.executar("DELETE FROM hotel_estadia_hospedes WHERE estadia_id = ?", (estadia_id,))
            for hid, responsavel in lista:
                self.banco.inserir("hotel_estadia_hospedes",
                                   {"estadia_id": estadia_id, "hospede_id": hid, "responsavel": responsavel})
        self.banco.log("hotel_checkin", f"quarto {e['uh']}: {titular['nome']} (conta {conta})", self.operador_id)
        return self.estadia(estadia_id)

    def checkin_direto(self, uh_id: int, hospede_id: int, saida=None, *, modalidade: str = "diaria",
                       periodo_id: int | None = None, adultos: int = 1, criancas: int = 0,
                       acompanhantes: list[dict] | tuple = (), cafe_incluso: bool | None = None, **viagem) -> dict:
        """Hóspede que chega sem reserva: reserva para agora e faz o check-in em seguida (tudo ou nada)."""
        agora = fmt.agora_dt()
        permitir = bool(viagem.pop("permitir_quarto_sujo", False))
        with self.banco.transacao():
            estadia_id = self.reservar(
                uh_id, self.hospede(hospede_id)["nome"], agora.date() if modalidade == "diaria" else agora, saida,
                modalidade=modalidade, periodo_id=periodo_id, adultos=adultos, criancas=criancas, hospede_id=hospede_id,
                cafe_incluso=cafe_incluso)
            return self.checkin(estadia_id, hospede_id, acompanhantes, permitir_quarto_sujo=permitir, **viagem)

    def _diarias_devidas(self, e: dict, ate: date) -> int:
        entrada = _dt(e["entrada_em"]).date()
        return max(0, (ate - entrada).days)

    def _lancar(self, e: dict, produto_id: int, quantidade: float, observacao: str) -> int:
        if not e["venda_id"] or not self.banco.valor(
                "SELECT 1 FROM vendas WHERE id = ? AND status IN ('aberta','conta_enviada')", (e["venda_id"],)):
            raise ErroNegocio(f"A conta da estadia (conta {e['conta']}) já foi fechada no caixa.")
        return self._caixa().adicionar_item(e["venda_id"], produto_id, quantidade, observacao)

    def lancar_diarias(self, estadia_id: int, ate=None) -> int:
        """Lança na conta as diárias já vencidas (as noites até `ate`, padrão hoje, sem passar da saída prevista).
        Devolve quantas lançou. Para a conta mostrar o que já se deve numa estadia longa."""
        e = self.estadia(estadia_id)
        if e["situacao"] != "hospedada" or e["modalidade"] != "diaria":
            raise ErroNegocio("Só se lançam diárias de hóspede em diária.")
        limite = min(_data(ate) if ate else fmt.agora_dt().date(), _dt(e["saida_prevista"]).date())
        faltam = self._diarias_devidas(e, limite) - e["diarias_lancadas"]
        if faltam <= 0:
            return 0
        with self.banco.transacao():
            self._lancar(e, e["produto_id"], faltam, f"Quarto {e['uh']}: {faltam} diária(s)")
            self.banco.executar("UPDATE hotel_estadias SET diarias_lancadas = diarias_lancadas + ?, atualizado_em = ? "
                                "WHERE id = ?", (faltam, fmt.agora(), estadia_id))
        return faltam

    def lancar_diarias_vencidas(self) -> int:
        """Todas as estadias em diária de uma vez (a "auditoria da noite"). Devolve o total de diárias lançadas."""
        total = 0
        for r in self.banco.todos("SELECT id FROM hotel_estadias WHERE situacao = 'hospedada' AND modalidade = 'diaria'"):
            total += self.lancar_diarias(r["id"])
        return total

    def lancar_cafe(self, estadia_id: int, pessoas: int) -> int:
        e = self.estadia(estadia_id)
        if e["situacao"] != "hospedada":
            raise ErroNegocio("O café avulso entra na conta de quem está hospedado.")
        pid = self.banco.cfg_int("hotel_produto_cafe", 0)
        if not self._preco(pid):
            raise ErroNegocio("Defina o preço do café da manhã avulso em Quartos e tarifas.")
        if not 1 <= int(pessoas) <= 20:
            raise ErroValidacao("Informe quantas pessoas tomaram o café.")
        return self._lancar(e, pid, int(pessoas), f"Quarto {e['uh']}: café da manhã")

    def lancar_produto(self, estadia_id: int, produto_id: int, quantidade: float, observacao: str | None = None) -> int:
        """Qualquer produto do caixa na conta do quarto (frigobar, lavanderia, estacionamento...)."""
        e = self.estadia(estadia_id)
        if e["situacao"] != "hospedada":
            raise ErroNegocio("Só se lança na conta de quem está hospedado.")
        return self._lancar(e, produto_id, quantidade, observacao or f"Quarto {e['uh']}")

    def previa_checkout(self, estadia_id: int, cobrar_diaria_extra: bool = False) -> dict:
        """O que o check-out vai lançar e quanto a conta fica: para a tela mostrar antes de confirmar."""
        e = self.estadia(estadia_id)
        if e["situacao"] != "hospedada":
            raise ErroNegocio("O check-out é de quem está hospedado.")
        c = self.config()
        agora = fmt.agora_dt()
        r = {"estadia": e, "linhas": [], "atraso_min": 0, "horas_extras": 0}
        if e["modalidade"] == "diaria":
            noites = max(1, self._diarias_devidas(e, agora.date()))
            limite = datetime.combine(agora.date(), datetime.strptime(c["checkout"], "%H:%M").time())
            if agora.date() >= _dt(e["saida_prevista"]).date() and agora > limite + timedelta(minutes=c["tolerancia_min"]):
                r["atraso_min"] = int((agora - limite).total_seconds() // 60)
            if cobrar_diaria_extra:
                noites += 1
            faltam = max(0, noites - e["diarias_lancadas"])
            r["noites"] = noites
            if faltam:
                r["linhas"].append({"produto_id": e["produto_id"], "quantidade": faltam,
                                    "descricao": f"{faltam} diária(s) do {e['tipo']}",
                                    "valor_cent": fmt.mult_cent(e["preco_cent"], faltam)})
        else:
            if not e["diarias_lancadas"]:
                r["linhas"].append({"produto_id": e["produto_id"], "quantidade": 1,
                                    "descricao": f"Período {e['periodo'] or ''}".strip(), "valor_cent": e["preco_cent"]})
            passou = (agora - _dt(e["saida_prevista"])).total_seconds() / 60
            if passou > c["tolerancia_min"]:
                r["atraso_min"] = int(passou)
                horas = math.ceil(passou / 60) - e["horas_extras_lancadas"]
                pid = self.banco.cfg_int("hotel_produto_hora_extra", 0)
                if horas > 0 and self._preco(pid):
                    r["horas_extras"] = horas
                    r["linhas"].append({"produto_id": pid, "quantidade": horas, "descricao": f"{horas} hora(s) adicional(is)",
                                        "valor_cent": fmt.mult_cent(self._preco(pid), horas)})
        r["conta_atual_cent"] = self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (e["venda_id"],), 0) or 0
        r["pago_cent"] = self._pago(e["venda_id"])
        r["a_lancar_cent"] = sum(linha["valor_cent"] for linha in r["linhas"])
        r["total_cent"] = r["conta_atual_cent"] + r["a_lancar_cent"]
        r["saldo_cent"] = r["total_cent"] - r["pago_cent"]
        return r

    def checkout(self, estadia_id: int, cobrar_diaria_extra: bool = False) -> dict:
        """Saída: lança as diárias (ou o período e as horas adicionais) na conta, encerra a estadia e deixa o quarto
        sujo para a arrumação. O pagamento é no caixa, na conta (comanda) da estadia: devolve o número dela."""
        self._exigir_ligado()
        previa = self.previa_checkout(estadia_id, cobrar_diaria_extra)
        e = previa["estadia"]
        agora = fmt.agora()
        with self.banco.transacao():
            for linha in previa["linhas"]:
                self._lancar(e, linha["produto_id"], linha["quantidade"], f"Quarto {e['uh']}: {linha['descricao']}")
            dados = {"situacao": "encerrada", "saida_em": agora, "atualizado_em": agora}
            if e["modalidade"] == "diaria":
                dados["diarias_lancadas"] = previa.get("noites", e["diarias_lancadas"])
            else:
                dados["diarias_lancadas"] = 1
                dados["horas_extras_lancadas"] = e["horas_extras_lancadas"] + previa["horas_extras"]
            self.banco.atualizar("hotel_estadias", estadia_id, dados)
            self.banco.executar("UPDATE hotel_uhs SET limpeza = 'sujo' WHERE id = ? AND limpeza <> 'manutencao'",
                                (e["uh_id"],))
        self.banco.log("hotel_checkout", f"quarto {e['uh']}: {e['titular_nome']} (conta {e['conta']})", self.operador_id)
        total = self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (e["venda_id"],), 0) or 0
        return {"venda_id": e["venda_id"], "conta": e["conta"], "total_cent": total, "pago_cent": self._pago(e["venda_id"])}

    def _pago(self, venda_id: int | None) -> int:
        """O que já entrou na conta (adiantamentos inclusive), sem o troco."""
        if not venda_id:
            return 0
        return self.banco.valor("SELECT COALESCE(SUM(valor_cent - troco_cent), 0) FROM pagamentos_venda WHERE venda_id = ?",
                                (venda_id,), 0) or 0

    def cancelar(self, estadia_id: int, motivo: str) -> None:
        e = self.estadia(estadia_id)
        if e["situacao"] != "reservada":
            raise ErroNegocio("Só se cancela reserva. Hóspede já hospedado sai pelo check-out.")
        motivo = " ".join((motivo or "").split())
        if len(motivo) < 3:
            raise ErroValidacao("Diga o motivo do cancelamento.", {"motivo": "obrigatório"})
        self.banco.executar("UPDATE hotel_estadias SET situacao = 'cancelada', motivo_cancelamento = ?, atualizado_em = ? "
                            "WHERE id = ?", (motivo, fmt.agora(), estadia_id))
        self.banco.log("hotel_cancelamento", f"quarto {e['uh']}: {e['titular_nome']} ({motivo})", self.operador_id)

    def nao_compareceu(self, estadia_id: int) -> None:
        e = self.estadia(estadia_id)
        if e["situacao"] != "reservada":
            raise ErroNegocio("Só a reserva pode ficar como não compareceu.")
        if _dt(e["entrada_prevista"]).date() > fmt.agora_dt().date():
            raise ErroNegocio("A data da chegada ainda não chegou.")
        self.banco.executar("UPDATE hotel_estadias SET situacao = 'nao_compareceu', atualizado_em = ? WHERE id = ?",
                            (fmt.agora(), estadia_id))
        self.banco.log("hotel_no_show", f"quarto {e['uh']}: {e['titular_nome']}", self.operador_id)

    def trocar_quarto(self, estadia_id: int, nova_uh_id: int, permitir_quarto_sujo: bool = False) -> None:
        e = self.estadia(estadia_id)
        if e["situacao"] not in ATIVAS:
            raise ErroNegocio("Só se troca o quarto de reserva ou hospedagem em andamento.")
        nova = self.uh(nova_uh_id)
        if nova["id"] == e["uh_id"]:
            return
        if e["adultos"] + e["criancas"] > nova["capacidade"]:
            raise ErroNegocio(f"O quarto {nova['numero']} é para até {nova['capacidade']} pessoas.")
        if e["situacao"] == "hospedada" and nova["limpeza"] != "limpo" and not permitir_quarto_sujo:
            raise ErroNegocio(f"O quarto {nova['numero']} está {LIMPEZA[nova['limpeza']].lower()}.")
        inicio, fim = self._intervalo(e)
        if e["situacao"] == "hospedada":
            inicio = fmt.agora_dt()
        with self.banco.transacao():
            self._exigir_livre(nova, inicio, fim, ignorar=estadia_id)
            self.banco.executar("UPDATE hotel_estadias SET uh_id = ?, atualizado_em = ? WHERE id = ?",
                                (nova["id"], fmt.agora(), estadia_id))
            if e["situacao"] == "hospedada":
                self.banco.executar("UPDATE hotel_uhs SET limpeza = 'sujo' WHERE id = ? AND limpeza <> 'manutencao'",
                                    (e["uh_id"],))
                if e["conta_aberta"]:
                    caixa = self._caixa()
                    caixa.definir_apelido(e["venda_id"], f"Q{nova['numero']} {e['titular_nome']}"[:caixa.APELIDO_MAXIMO])
        self.banco.log("hotel_troca_quarto", f"{e['titular_nome']}: {e['uh']} -> {nova['numero']}", self.operador_id)

    def alterar_datas(self, estadia_id: int, entrada=None, saida=None) -> None:
        """Reserva: muda entrada e saída. Hospedado em diária: muda só a saída (prorrogar ou antecipar)."""
        e = self.estadia(estadia_id)
        if e["modalidade"] != "diaria":
            raise ErroNegocio("No período, o tempo é o do período escolhido.")
        if e["situacao"] == "reservada":
            inicio, fim = self._datas_diaria(entrada or e["entrada_prevista"], saida or e["saida_prevista"])
            if inicio.date() < fmt.agora_dt().date():
                raise ErroValidacao("A entrada não pode ser num dia que já passou.")
            dados = {"entrada_prevista": _iso(inicio), "saida_prevista": _iso(fim)}
        elif e["situacao"] == "hospedada":
            entrada_real = _dt(e["entrada_em"])
            _, fim = self._datas_diaria(entrada_real.date(), saida)
            if fim.date() < fmt.agora_dt().date():
                raise ErroValidacao("A nova saída não pode ser num dia que já passou.")
            if (fim.date() - entrada_real.date()).days < e["diarias_lancadas"]:
                raise ErroNegocio("Já há mais diárias lançadas na conta do que a nova saída permite.")
            inicio = fmt.agora_dt()
            dados = {"saida_prevista": _iso(fim)}
        else:
            raise ErroNegocio("Esta estadia não aceita mais mudança de data.")
        with self.banco.transacao():
            self._exigir_livre(self.uh(e["uh_id"]), inicio, fim, ignorar=estadia_id)
            self.banco.atualizar("hotel_estadias", estadia_id, {**dados, "atualizado_em": fmt.agora()})
        self.banco.log("hotel_datas", f"quarto {e['uh']}: {e['titular_nome']} até {fmt.fmt_data(_iso(fim))}",
                       self.operador_id)

    # ============================================================ painéis
    def painel_hoje(self) -> dict:
        """Recepção: chegadas e saídas do dia, hospedados, períodos correndo (com o tempo) e os quartos."""
        agora = fmt.agora_dt()
        hoje = agora.date().isoformat()
        amanha = (agora.date() + timedelta(days=1)).isoformat()
        c = self.config()
        chegadas = [e for e in self.estadias(("reservada",), limite=500)
                    if e["entrada_prevista"][:10] <= hoje]
        hospedados = self.estadias(("hospedada",), limite=500)
        saidas = [e for e in hospedados if e["saida_prevista"][:10] <= hoje and e["modalidade"] == "diaria"]
        periodos = []
        for e in hospedados:
            if e["modalidade"] != "periodo":
                continue
            restante = (_dt(e["saida_prevista"]) - agora).total_seconds()
            e["restante_seg"] = restante
            e["relogio"] = fmt_relogio(restante)
            e["alerta"] = ("estourou" if restante < 0 else "alerta" if restante <= c["alerta_min"] * 60 else "uso")
            periodos.append(e)
        uhs = self.uhs()
        ocupadas = {e["uh_id"] for e in hospedados}
        reservadas_hoje = {e["uh_id"] for e in chegadas}
        for u in uhs:
            u["ocupada"] = u["id"] in ocupadas
            u["chegada_hoje"] = u["id"] in reservadas_hoje
        livres = [u for u in uhs if not u["ocupada"] and u["limpeza"] != "manutencao"]
        return {
            "hoje": hoje, "amanha": amanha, "chegadas": chegadas, "saidas": saidas, "hospedados": hospedados,
            "periodos": sorted(periodos, key=lambda e: e["restante_seg"]), "uhs": uhs,
            "resumo": {"quartos": len(uhs), "ocupados": len(ocupadas), "livres": len(livres),
                       "prontos": sum(1 for u in livres if u["limpeza"] == "limpo"),
                       "sujos": sum(1 for u in uhs if u["limpeza"] in ("sujo", "arrumando")),
                       "manutencao": sum(1 for u in uhs if u["limpeza"] == "manutencao"),
                       "hospedes": sum(e["adultos"] + e["criancas"] for e in hospedados),
                       "chegadas": len(chegadas), "saidas": len(saidas)},
        }

    def mapa(self, inicio=None, dias: int = 14) -> dict:
        """Grade quartos x dias (noites). Cada estadia vira um bloco das colunas `col_ini` a `col_fim` (exclusivo)."""
        primeiro = _data(inicio) if inicio else fmt.agora_dt().date()
        dias = max(1, min(int(dias), MAX_DIAS_MAPA))
        ultimo = primeiro + timedelta(days=dias)
        datas = [primeiro + timedelta(days=i) for i in range(dias)]
        linhas = []
        estadias = [dict(r) for r in self.banco.todos(
            f"""SELECT e.* FROM hotel_estadias e WHERE e.situacao IN ('reservada','hospedada','encerrada')
                AND COALESCE(e.entrada_em, e.entrada_prevista) < ? AND COALESCE(e.saida_em, e.saida_prevista) >= ?""",
            (f"{ultimo.isoformat()} 00:00:00", f"{primeiro.isoformat()} 00:00:00"))]
        agora = fmt.agora_dt()
        for u in self.uhs():
            blocos = []
            for e in (x for x in estadias if x["uh_id"] == u["id"]):
                ini = _dt(e["entrada_em"] or e["entrada_prevista"]).date()
                if e["situacao"] == "encerrada":
                    fim = _dt(e["saida_em"]).date()
                elif e["situacao"] == "hospedada":
                    fim = max(_dt(e["saida_prevista"]).date(), agora.date())
                else:
                    fim = _dt(e["saida_prevista"]).date()
                if e["modalidade"] == "periodo" or fim <= ini:
                    fim = ini + timedelta(days=1)          # período e saída no mesmo dia ocupam a coluna do dia
                col_ini = max(0, (ini - primeiro).days)
                col_fim = min(dias, (fim - primeiro).days)
                if col_fim <= col_ini:
                    continue
                blocos.append({"estadia_id": e["id"], "situacao": e["situacao"], "modalidade": e["modalidade"],
                               "titular": e["titular_nome"], "col_ini": col_ini, "col_fim": col_fim,
                               "continua_antes": ini < primeiro, "continua_depois": fim > ultimo})
            linhas.append({"uh": u, "blocos": sorted(blocos, key=lambda b: b["col_ini"])})
        return {"inicio": primeiro.isoformat(), "datas": [d.isoformat() for d in datas], "linhas": linhas}

    # ============================================================ relatórios
    def ocupacao(self, de, ate) -> dict:
        """Ocupação por noite no intervalo [de, ate] (datas inclusive): noites disponíveis, vendidas, taxa, receita das
        diárias lançadas, diária média (ADR) e receita por quarto disponível (RevPAR); e os períodos."""
        d_de, d_ate = _data(de), _data(ate)
        if d_ate < d_de:
            raise ErroValidacao("A data final vem antes da inicial.")
        if (d_ate - d_de).days > 366:
            raise ErroValidacao("Consulte no máximo um ano por vez.")
        quartos = self.banco.valor("SELECT COUNT(*) FROM hotel_uhs WHERE ativo = 1", (), 0)
        dias = (d_ate - d_de).days + 1
        por_dia = {(d_de + timedelta(days=i)).isoformat(): 0 for i in range(dias)}
        agora = fmt.agora_dt()
        for r in self.banco.todos(
                """SELECT * FROM hotel_estadias WHERE modalidade = 'diaria' AND situacao IN ('hospedada','encerrada')
                   AND entrada_em IS NOT NULL"""):
            e = dict(r)
            ini = _dt(e["entrada_em"]).date()
            fim = _dt(e["saida_em"]).date() if e["saida_em"] else max(_dt(e["saida_prevista"]).date(), agora.date())
            fim = max(fim, ini + timedelta(days=1))
            noite = max(ini, d_de)
            while noite < fim and noite <= d_ate:
                por_dia[noite.isoformat()] += 1
                noite += timedelta(days=1)
        vendidas = sum(por_dia.values())
        disponiveis = quartos * dias
        inicio_iso, fim_iso = f"{d_de.isoformat()} 00:00:00", f"{(d_ate + timedelta(days=1)).isoformat()} 00:00:00"
        receita_diarias = self.banco.valor(
            """SELECT COALESCE(SUM(i.total_cent), 0) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
               WHERE i.cancelado = 0 AND v.status <> 'cancelada' AND i.criado_em >= ? AND i.criado_em < ?
               AND i.produto_id IN (SELECT produto_diaria_id FROM hotel_tipos WHERE produto_diaria_id IS NOT NULL)""",
            (inicio_iso, fim_iso), 0)
        receita_periodos = self.banco.valor(
            """SELECT COALESCE(SUM(i.total_cent), 0) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
               WHERE i.cancelado = 0 AND v.status <> 'cancelada' AND i.criado_em >= ? AND i.criado_em < ?
               AND (i.produto_id IN (SELECT produto_id FROM hotel_periodos WHERE produto_id IS NOT NULL)
                    OR i.produto_id = ?)""",
            (inicio_iso, fim_iso, self.banco.cfg_int("hotel_produto_hora_extra", 0)), 0)
        periodos = self.banco.valor(
            """SELECT COUNT(*) FROM hotel_estadias WHERE modalidade = 'periodo' AND situacao IN ('hospedada','encerrada')
               AND entrada_em >= ? AND entrada_em < ?""", (inicio_iso, fim_iso), 0)
        return {
            "de": d_de.isoformat(), "ate": d_ate.isoformat(), "quartos": quartos, "dias": dias,
            "noites_disponiveis": disponiveis, "noites_vendidas": vendidas,
            "ocupacao_pct": round(100 * vendidas / disponiveis, 1) if disponiveis else 0.0,
            "receita_diarias_cent": receita_diarias,
            "diaria_media_cent": fmt.dividir_cent(receita_diarias, vendidas) if vendidas else 0,
            "revpar_cent": fmt.dividir_cent(receita_diarias, disponiveis) if disponiveis else 0,
            "periodos": periodos, "receita_periodos_cent": receita_periodos,
            "por_dia": [{"data": d, "ocupados": n, "pct": round(100 * n / quartos, 1) if quartos else 0.0}
                        for d, n in por_dia.items()],
        }

    def cafe_do_dia(self, dia=None) -> dict:
        """Quem toma café na manhã de `dia` (padrão hoje): os hospedados em diária que dormiram a noite anterior, com o
        café incluso ou não (o avulso se cobra à parte)."""
        d = _data(dia) if dia else fmt.agora_dt().date()
        quartos = []
        for r in self.banco.todos(
                """SELECT e.*, u.numero AS uh FROM hotel_estadias e JOIN hotel_uhs u ON u.id = e.uh_id
                   WHERE e.modalidade = 'diaria' AND e.situacao IN ('hospedada','encerrada') AND e.entrada_em IS NOT NULL"""):
            e = dict(r)
            entrou = _dt(e["entrada_em"]).date()
            saiu = _dt(e["saida_em"]).date() if e["saida_em"] else _dt(e["saida_prevista"]).date()
            if entrou < d <= max(saiu, entrou + timedelta(days=1)):
                quartos.append({"uh": e["uh"], "titular": e["titular_nome"], "pessoas": e["adultos"] + e["criancas"],
                                "adultos": e["adultos"], "criancas": e["criancas"], "incluso": bool(e["cafe_incluso"]),
                                "estadia_id": e["id"], "situacao": e["situacao"]})
        quartos = self._ordenar_uhs([{**q, "numero": q["uh"], "ordem": 0} for q in quartos])
        return {"dia": d.isoformat(), "quartos": quartos,
                "pessoas": sum(q["pessoas"] for q in quartos),
                "inclusos": sum(q["pessoas"] for q in quartos if q["incluso"]),
                "avulsos": sum(q["pessoas"] for q in quartos if not q["incluso"])}

    COLUNAS_FICHA = (("entrada", "Entrada"), ("saida", "Saída"), ("uh", "Quarto"), ("nome", "Nome"),
                     ("cpf", "CPF"), ("documento_tipo", "Tipo de documento"), ("documento", "Documento"),
                     ("documento_emissor", "Órgão/país emissor"), ("nascimento", "Nascimento"), ("genero", "Gênero"),
                     ("nacionalidade", "Nacionalidade"), ("telefone", "Telefone"), ("email", "E-mail"),
                     ("profissao", "Profissão"), ("cidade", "Cidade de residência"), ("uf", "UF"), ("pais", "País"),
                     ("motivo_viagem", "Motivo da viagem"), ("meio_transporte", "Meio de transporte"),
                     ("procedencia", "Última procedência"), ("proximo_destino", "Próximo destino"),
                     ("titular", "Titular"), ("responsavel", "Responsável (menor)"))

    def fichas(self, de, ate) -> list[dict]:
        """Uma linha por hóspede (titular e acompanhantes) das estadias com check-in entre `de` e `ate`: os dados para
        conferir ou digitar na FNRH Digital."""
        d_de, d_ate = _data(de), _data(ate)
        estadias = self.banco.todos(
            """SELECT e.*, u.numero AS uh FROM hotel_estadias e JOIN hotel_uhs u ON u.id = e.uh_id
               WHERE e.entrada_em >= ? AND e.entrada_em < ? AND e.situacao IN ('hospedada','encerrada')
               ORDER BY e.entrada_em""",
            (f"{d_de.isoformat()} 00:00:00", f"{(d_ate + timedelta(days=1)).isoformat()} 00:00:00"))
        linhas = []
        for e in estadias:
            pessoas = [(e["hospede_id"], None, "Sim")]
            pessoas += [(a["hospede_id"], a["responsavel"], "Não") for a in self.banco.todos(
                "SELECT hospede_id, responsavel FROM hotel_estadia_hospedes WHERE estadia_id = ?", (e["id"],))]
            for hid, responsavel, titular in pessoas:
                if not hid:
                    continue
                h = self.hospede(hid)
                linhas.append({
                    "entrada": fmt.fmt_datahora(e["entrada_em"])[:16], "saida": fmt.fmt_datahora(
                        e["saida_em"] or e["saida_prevista"])[:16], "uh": e["uh"], "nome": h["nome"],
                    "cpf": fmt_cpf(h["cpf"]), "documento_tipo": h["documento_tipo"], "documento": h["documento"] or "",
                    "documento_emissor": h["documento_emissor"] or "", "nascimento": fmt.fmt_data(h["nascimento"]),
                    "genero": h["genero"] or "", "nacionalidade": h["nacionalidade"], "telefone": h["telefone"] or "",
                    "email": h["email"] or "", "profissao": h["profissao"] or "", "cidade": h["cidade"] or "",
                    "uf": h["uf"] or "", "pais": h["pais"], "motivo_viagem": e["motivo_viagem"] or "",
                    "meio_transporte": e["meio_transporte"] or "", "procedencia": e["procedencia"] or "",
                    "proximo_destino": e["proximo_destino"] or "", "titular": titular, "responsavel": responsavel or ""})
        return linhas

    def exportar_fichas(self, de, ate, caminho: str | Path) -> Path:
        """Planilha (CSV com ; e acentos para o Excel) das fichas do período."""
        caminho = Path(caminho)
        linhas = self.fichas(de, ate)
        with caminho.open("w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow([rotulo for _, rotulo in self.COLUNAS_FICHA])
            for linha in linhas:
                escritor.writerow([linha[chave] for chave, _ in self.COLUNAS_FICHA])
        self.banco.log("hotel_fichas_exportadas", f"{len(linhas)} ficha(s) de {de} a {ate}", self.operador_id)
        return caminho
