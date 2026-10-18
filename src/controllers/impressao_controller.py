"""Textos para a impressora de cupom (fita de 40 colunas) e envio para tela/arquivo/Windows.

Não há emissão fiscal: tudo sai como 'CUPOM NÃO FISCAL'. Leitura X e Redução Z são relatórios
gerenciais calculados a partir do banco, não comandos de impressora fiscal (ECF).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from src.controllers import conferencia_turno
from src.controllers.conferencia_turno import faixa
from src.controllers.caixa_controller import CaixaController
from src.controllers.config_controller import ConfigController
from src.controllers.relatorio_controller import RelatorioController
from src.core import formatacao as fmt
from src.core.posicao import nome as nome_posicao
from src.core.relatorio import para_texto
from src.database.conexao import RAIZ
from src.controllers.fila_impressao_controller import FilaImpressao
from src.hardware import impressora_termica as term
from src.hardware.imagem_escpos import logotipo_escpos
from src.hardware.impressora_termica import ErroImpressao, ImpressoraTermica

# Documentos que levam o logotipo da loja no topo (os internos, como sangria e fechamento, não).
TIPOS_COM_LOGOTIPO = {"cupom", "pre_conta", "entrega"}

# Ênfase ESC/POS por tipo de documento (quais linhas saem em negrito/dobro de altura).
_ESTILOS = {
    "cupom": {"negrito_linhas": 1, "grande_prefixos": ("TOTAL",)},
    "pre_conta": {"negrito_linhas": 1, "grande_prefixos": ("TOTAL",)},
    "entrega": {"negrito_linhas": 1, "grande_prefixos": ("TOTAL", "LEVAR TROCO")},
    "fechamento": {"negrito_linhas": 1, "grande_prefixos": ("ESPERADO NA GAVETA", "DECLARADO", "SOBROU", "FALTOU",
                                                           "CAIXA CONFERIDO", "TOTAL RECEBIDO")},
    "pedido": {"negrito_linhas": 1},
    "comprovante": {"negrito_linhas": 1, "grande_prefixos": ("Valor",)},
    # Ticket de saída (1002): título e nome da casa em negrito; aviso, data/hora e a comanda liberada em letra alta.
    "saida": {"negrito_linhas": 6, "grande_prefixos": ("FAVOR ENTREGAR", "TICKET NA SAIDA", "DATA:", "CARTAO:", "MESA:")},
    "via_comissao": {"negrito_linhas": 1, "grande_prefixos": ("Valor desta", "Pontos desta")},
    # Pagamento da garota: o recibo e o comprovante de saída da gaveta saem com as linhas que ela confere em letra mais alta.
    "recibo_garota": {"negrito_linhas": 1, "grande_prefixos": ("Garota:", "COMISSÃO", "SHOWS", "TOTAL PAGO", "Dinheiro", "Vale",
                                                              "Pix", "Saiu do dinheiro", "Pago fora")},
    "saida_garota": {"negrito_linhas": 1, "grande_prefixos": ("Valor", "Motivo:", "Operador:")},
    "relatorio": {"negrito_linhas": 1},
}

LIMITE_MOVIMENTOS = 40        # sangrias/suprimentos listados no fechamento

M, Q = fmt.fmt_num, fmt.fmt_qtd


def _lr(esq: str, dir_: str, w: int) -> str:
    esq = esq[: max(w - len(dir_) - 1, 1)]
    return esq.ljust(w - len(dir_)) + dir_


def _q(q) -> str:
    """Quantidade sem zeros inúteis: 3 e não 3,000; 1,25 continua 1,25."""
    q = float(q or 0)
    return str(int(q)) if q == int(q) else Q(q).rstrip("0").rstrip(",")


def _titulo(texto: str, w: int) -> list[str]:
    return ["=" * w, texto.center(w), "=" * w]


class ImpressaoController:
    def __init__(self, banco):
        self.banco = banco
        self.config = ConfigController(banco)
        self.caixa = CaixaController(banco)
        self.fila = FilaImpressao(banco)

    # ------------------------------------------------------------- base
    def largura(self) -> int:
        return int(self.config.maquina()["colunas_fita"] or 40)

    def cabecalho(self, w: int) -> list[str]:
        l = self.config.loja()
        linhas = [(l["nome_fantasia"] or l["razao_social"] or "PDV").upper().center(w)]
        if l["razao_social"] and l["razao_social"] != l["nome_fantasia"]:
            linhas.append(l["razao_social"].center(w))
        if l["slogan"]:
            linhas.append(l["slogan"].center(w))
        endereco = ", ".join(x for x in (l["endereco"], l["bairro"], l["cidade"]) if x)
        if endereco:
            linhas.append(endereco[:w].center(w))
        if l["cnpj"]:
            linhas.append(f"CNPJ {l['cnpj']}".center(w))
        if l["telefone"]:
            linhas.append(f"Tel. {l['telefone']}".center(w))
        return linhas

    # ------------------------------------------------------------ cupons
    def _corpo_itens(self, venda_id: int, w: int) -> list[str]:
        """Itens em colunas: QTD, DESCRIÇÃO, UNIT. e TOTAL (sem a coluna UNIT. na fita de 58mm). Nome comprido vai numa
        linha só dele e os números na de baixo, para nada ser cortado."""
        com_unit = w >= 40
        largura_nome = w - 4 - 10 - (9 if com_unit else 0)
        cab = "QTD " + "DESCRIÇÃO".ljust(largura_nome) + ("UNIT.".rjust(9) if com_unit else "") + "TOTAL".rjust(10)
        out = [cab[:w], "-" * w]
        for it in self.caixa.itens(venda_id):
            numeros = (M(it["preco_unit_cent"]).rjust(9) if com_unit else "") + M(it["total_cent"]).rjust(10)
            qtd = _q(it["quantidade"]).ljust(4)
            if len(it["nome"]) <= largura_nome - 1:
                out.append(qtd + it["nome"].ljust(largura_nome) + numeros)
            else:
                out += [(qtd + it["nome"])[:w], " " * (4 + largura_nome) + numeros]
            if it["partes_nomes"]:
                out += [f"    1/{it['partes']} {n}"[:w] for n in it["partes_nomes"]]
            if it["observacao"]:
                out.append(f"    * {it['observacao']}"[:w])
        return out

    def _totais(self, v: dict, w: int) -> list[str]:
        out = [_lr("Subtotal", M(v["subtotal_cent"]), w)]
        if v.get("rodizio"):
            out.append(_lr(f"Rodízio ({v['pessoas']} pessoa(s))", M(v["rodizio_total_cent"]), w))
        if v["desconto_cent"]:
            out.append(_lr("Desconto (-)", M(v["desconto_cent"]), w))
        if v["servico_cent"]:
            out.append(_lr("Serviço (+)", M(v["servico_cent"]), w))
        if v["taxa_cent"]:
            out.append(_lr("Compl. consumação mín. (+)" if v.get("comanda") else "Taxa de entrega (+)", M(v["taxa_cent"]), w))
        if v.get("acrescimo_cent"):
            out.append(_lr("Taxa do crédito (+)", M(v["acrescimo_cent"]), w))
        out.append(_lr("TOTAL", f"R$ {M(v['total_cent'])}", w))
        return out

    def _origem(self, v: dict) -> str:
        if v["modalidade"] == "mesa":
            return nome_posicao(v.get("comanda"), v["posicao"])
        if v["modalidade"] == "entrega":
            return f"Entrega pedido {v['posicao']}"
        if v["modalidade"] == "caderneta":
            return "Caderneta"
        return "Balcão"

    def cupom(self, venda_id: int, segunda_via: bool = False) -> str:
        w = self.largura()
        v = self.caixa.obter(venda_id)
        op = self.banco.valor("SELECT nome FROM operadores WHERE id = ?", (v["operador_id"],), "")
        titulo = "CUPOM NÃO FISCAL" + (" - CANCELADO" if v["status"] == "cancelada" else "")
        linhas = self.cabecalho(w) + _titulo(titulo, w)
        if segunda_via:
            linhas.append("** SEGUNDA VIA - REIMPRESSÃO **".center(w))
        linhas += [_lr(f"Cupom: {v['cupom'] or '-'}", self._origem(v), w),
                   _lr(fmt.fmt_datahora(v["fechada_em"] or v["aberta_em"])[:16], f"Operador: {op}", w), "-" * w]
        if v["cliente_id"]:
            c = self.banco.um("SELECT nome FROM clientes WHERE id = ?", (v["cliente_id"],))
            linhas.append(f"Cliente: {c['nome']}"[:w])
        linhas += self._corpo_itens(venda_id, w) + ["-" * w] + self._totais(v, w)
        pags = self.caixa.pagamentos(venda_id)
        if pags:
            linhas += ["", faixa("PAGAMENTO", w)]
            linhas += [_lr(p["tipo"], M(p["valor_cent"]), w) for p in pags]
            if v["troco_cent"]:
                linhas.append(_lr("Troco", M(v["troco_cent"]), w))
            if v["vale_cent"]:
                linhas.append(_lr("Contra-vale emitido", M(v["vale_cent"]), w))
        elif v["modalidade"] == "caderneta" and v["status"] == "fechada":
            linhas.append("Lançado na caderneta do cliente".center(w))
        if v["mensagem"]:
            linhas.append(f"Msg: {v['mensagem']}"[:w])
        rodape = self.banco.cfg("mensagem_rodape") or "Obrigado e volte sempre!"
        linhas += ["=" * w, rodape.center(w), "=" * w]
        return "\n".join(linhas)

    def pre_conta(self, venda_id: int) -> str:
        """Conta enviada à mesa ou comanda para o cliente conferir antes de pagar."""
        w = self.largura()
        v = self.caixa.obter(venda_id)
        titulo = "CONTA DA COMANDA" if v.get("comanda") else "CONTA DA MESA"
        linhas = self.cabecalho(w) + _titulo(titulo, w) + [("(confira antes de pagar - não é cupom fiscal)" if w >= 46
                                                             else "(não é cupom fiscal)").center(w),
                                                            _lr(self._origem(v), fmt.fmt_datahora(fmt.agora())[:16], w), "-" * w]
        linhas += self._corpo_itens(venda_id, w) + ["-" * w] + self._totais(v, w)
        if v["pessoas"] > 1:
            linhas.append(_lr(f"Por pessoa ({v['pessoas']})", M(fmt.dividir_cent(v["total_cent"], v["pessoas"])), w))
        return "\n".join(linhas + ["=" * w])

    def pedido_entrega(self, venda_id: int) -> str:
        w = self.largura()
        v = self.caixa.obter(venda_id)
        c = self.banco.um(
            """SELECT c.*, b.nome AS bairro FROM clientes c LEFT JOIN bairros b ON b.id = c.bairro_id WHERE c.id = ?""",
            (v["cliente_id"],))
        linhas = self.cabecalho(w) + ["=" * w, "E N T R E G A".center(w),
                                      _lr(fmt.fmt_datahora(v["aberta_em"]), f"Pedido {v['posicao']}", w), "-" * w,
                                      f"Cliente : {c['nome']}"[:w], f"Número  : {c['numero_consulta']}"[:w],
                                      f"Endereço: {c['endereco'] or ''} {c['complemento'] or ''}".strip()[:w * 2],
                                      f"Bairro  : {c['bairro'] or ''}", f"Telefone: {c['telefone'] or ''}", "-" * w]
        linhas += self._corpo_itens(venda_id, w) + ["-" * w] + self._totais(v, w) + ["=" * w]
        if v["troco_para_cent"]:
            linhas += [f"Pagamento: levar troco para {M(v['troco_para_cent'])}".strip(),
                       _lr("LEVAR TROCO DE", M(max(v["troco_para_cent"] - v["total_cent"], 0)), w)]
        if v["mensagem"]:
            linhas.append(f"Mensagem: {v['mensagem']}")
        return "\n".join(linhas)

    def pedido_remoto(self, venda_id: int, item_ids: list[int] | None = None) -> dict[str, str]:
        """Tickets para a cozinha/bar: um por subgrupo marcado com 'impressora remota'.
        As observações dos itens (ao ponto, sem gelo...) só aparecem aqui, não no cupom do cliente."""
        w = self.largura()
        v = self.caixa.obter(venda_id)
        sql = """SELECT i.id, i.quantidade, i.observacao, pr.nome, s.nome AS subgrupo FROM itens_venda i
                 JOIN produtos_historico pr ON pr.id = i.produto_id JOIN subgrupos s ON s.id = pr.subgrupo_id
                 WHERE i.venda_id = ? AND i.cancelado = 0 AND s.impressora_remota = 1"""
        params: list = [venda_id]
        if item_ids:
            sql += f" AND i.id IN ({','.join('?' * len(item_ids))})"
            params += item_ids
        porsub: dict = {}
        for r in self.banco.todos(sql + " ORDER BY s.nome, i.id", params):
            porsub.setdefault(r["subgrupo"], []).append(r)
        saida = {}
        for sub, itens in porsub.items():
            linhas = [f"PEDIDO - {sub}".center(w), _lr(self._origem(v), fmt.fmt_hora(fmt.agora())[:5], w), "-" * w]
            for r in itens:
                linhas.append(f"{Q(r['quantidade'], 0) if r['quantidade'] == int(r['quantidade']) else Q(r['quantidade'])} x {r['nome']}"[:w])
                if r["observacao"]:
                    linhas.append(f"   >> {r['observacao']}"[:w])
            saida[sub] = "\n".join(linhas)
        return saida

    def setor_do_subgrupo(self, nome_subgrupo: str) -> dict | None:
        """O setor de impressão (Configurações > Módulos > Cozinha/Bar) do subgrupo, se tiver um cadastrado."""
        r = self.banco.um(
            """SELECT st.* FROM subgrupos s JOIN setores_impressao st ON st.id = s.setor_impressao_id
               WHERE s.nome = ? AND st.ativo = 1""", (nome_subgrupo,))
        return dict(r) if r else None

    # ------------------------------------------------- turno e relatórios
    def fechamento(self, resumo: dict) -> str:
        """Fita da troca de turno, em blocos: a conta da gaveta e o resultado primeiro (o que o gerente confere), depois as
        formas de pagamento, as vendas e a conferência (sangrias, produtos, cancelamentos, comissões). Linha zerada de recurso
        que a casa não usa não aparece."""
        w = self.largura()
        t = resumo["turno"]
        encerrado = "valor_final" in resumo               # a Leitura X é parcial: sem declaração, resultado e assinatura
        caixa = self.banco.valor("SELECT nome FROM operadores WHERE id = ?", (t.get("operador_id"),), "")
        linhas = self.cabecalho(w) + _titulo("FECHAMENTO DE TURNO" if encerrado else "PARCIAL DO TURNO (LEITURA X)", w)
        linhas += [_lr(f"Turno: {t['numero']}", f"Caixa: {caixa}" if caixa else "", w),
                   _lr("Abertura:", fmt.fmt_datahora(t["aberto_em"])[:16], w),
                   _lr("Fechamento:" if encerrado else "Emitida em:", fmt.fmt_datahora(t.get("fechado_em") or fmt.agora())[:16], w),
                   _lr("Cupons:", f"{resumo['cupom_inicial']} a {resumo['cupom_final']}" if resumo["cupom_final"] else "nenhum", w)]

        # 1) A conta da gaveta: de onde vem o valor esperado.
        na_gaveta = sum(r["valor"] for r in resumo["recebimentos"] if r.get("na_gaveta", 1))
        linhas += ["", faixa("CONFERÊNCIA DA GAVETA", w), _lr("Fundo de caixa (+)", M(resumo["valor_inicial"]), w),
                   _lr("Recebido em dinheiro (+)", M(na_gaveta), w)]
        if resumo["entradas"]:
            linhas.append(_lr("Suprimentos (+)", M(resumo["entradas"]), w))
        if resumo["saidas"]:
            linhas.append(_lr("Sangrias e saídas (-)", M(resumo["saidas"]), w))
        linhas += [_lr("", "-" * 12, w), _lr("ESPERADO NA GAVETA", M(resumo["esperado"]), w)]
        if encerrado:
            linhas.append(_lr("DECLARADO PELO CAIXA", M(resumo["valor_final"]), w))
            linhas += self._sobra_ou_falta(resumo["resultado"], w)

        # 2) Formas de pagamento.
        linhas += ["", faixa("FORMAS DE PAGAMENTO", w)]
        if not resumo["recebimentos"]:
            linhas.append("  Nenhum recebimento")
        for r in resumo["recebimentos"]:
            linhas.append(_lr(r["tipo"] + ("" if r.get("na_gaveta", 1) else " (fora da gaveta)"), M(r["valor"]), w))
        linhas.append(_lr("TOTAL RECEBIDO", M(resumo["total_recebido"]), w))
        if resumo.get("fora_da_gaveta"):
            linhas.append(_lr("  Fora da gaveta (cartão/Pix)", M(resumo["fora_da_gaveta"]), w))
        if resumo.get("adiantamentos_abertos"):
            linhas.append(_lr("  Adiant. contas abertas", M(resumo["adiantamentos_abertos"]), w))
        if resumo.get("recebido_turno_anterior"):
            linhas.append(_lr("Pago em turno anterior", M(resumo["recebido_turno_anterior"]), w))

        # 2b) Cartão e Pix lançados no sistema, para o gerente bater com o que a maquininha imprimiu.
        maquininha = resumo.get("maquininha") or {}
        if maquininha.get("linhas"):
            linhas += ["", faixa("CONFERIR NA MAQUININHA", w)]
            for r in maquininha["linhas"]:
                linhas.append(_lr(f"{r['tipo']} ({r['qtd']})", M(r["valor"]), w))
            linhas.append(_lr(f"TOTAL ({maquininha['qtd']})", M(maquininha["total"]), w))

        # 3) Vendas.
        linhas += ["", faixa("VENDAS", w), _lr("Produtos", M(resumo["venda"]), w)]
        liga = {"desconto": "usar_desconto", "venda_caderneta": "usar_caderneta", "pagtos_caderneta": "usar_caderneta"}
        for rotulo, chave in (("Desconto (-)", "desconto"), ("Serviço (+)", "servico"), ("Taxa de entrega / compl. consumação (+)", "taxa"),
                              ("Taxa do crédito (+)", "acrescimo"),
                              ("Repique (caixinha)", "repique"), ("Troco devolvido", "troco"), ("Contra-vale emitido", "vale_emitido"),
                              ("Venda caderneta", "venda_caderneta"), ("Pagtos caderneta (+)", "pagtos_caderneta")):
            if resumo[chave] or (chave in liga and self.banco.cfg_bool(liga[chave], False)) or chave == "servico":
                linhas.append(_lr(rotulo, M(resumo[chave]), w))
        linhas += [_lr("Cupons emitidos", str(resumo["tc"]), w), _lr("Ticket médio", M(resumo["tm"]), w)]
        if resumo["pessoas"] and resumo["pessoas"] != resumo["tc"]:
            linhas += [_lr("Pessoas", str(resumo["pessoas"]), w), _lr("Valor por pessoa", M(resumo["valor_por_pessoa"]), w)]

        linhas += self._movimentos_do_turno(t["id"], w)
        linhas += conferencia_turno.linhas_fita(resumo, w)      # posições abertas, cancelamentos, transferências
        if encerrado:
            linhas += self._assinaturas(resumo, w)
        return "\n".join(linhas + ["", "=" * w, f"Impresso em {fmt.fmt_datahora(fmt.agora())[:16]}".center(w), "=" * w])

    @staticmethod
    def _sobra_ou_falta(resultado: int, w: int) -> list[str]:
        """O resultado em palavras e em letra grande: o gerente bate o olho e sabe se sobrou ou faltou dinheiro."""
        if resultado > 0:
            texto = f"SOBROU R$ {M(resultado)}"
        elif resultado < 0:
            texto = f"FALTOU R$ {M(-resultado)}"
        else:
            texto = "CAIXA CONFERIDO (sem diferença)"
        return ["=" * w, texto.center(w), "=" * w]

    def _movimentos_do_turno(self, turno_id: int, w: int) -> list[str]:
        """Cada sangria (saída) e suprimento (entrada) do turno, com a hora, o motivo e quem fez."""
        movimentos = self.caixa.turnos.movimentos(turno_id)
        if not movimentos:
            return []
        linhas = ["", faixa(f"SANGRIAS E SUPRIMENTOS ({len(movimentos)})", w)]
        for m in movimentos[:LIMITE_MOVIMENTOS]:
            tipo = "Saída" if m["tipo"] == "saida" else "Entrada"
            linhas.append(_lr(f"  {fmt.fmt_datahora(m['criado_em'])[11:16]} {tipo}", M(m["valor_cent"]), w))
            detalhe = " - ".join(x for x in ((m["descricao"] or "").strip(), m["operador"] or "") if x)
            if detalhe:
                linhas.append(f"        {detalhe}"[:w])
        if len(movimentos) > LIMITE_MOVIMENTOS:
            linhas.append(f"  ... e mais {len(movimentos) - LIMITE_MOVIMENTOS}")
        return linhas

    def _assinaturas(self, resumo: dict, w: int) -> list[str]:
        """Rodapé da passagem de caixa: justificativa (se houve diferença) e as linhas de assinatura."""
        t = resumo["turno"]
        quem = self.banco.valor("SELECT nome FROM operadores WHERE id = ?", (t.get("fechado_por") or t.get("operador_id"),), "")
        linhas = ["", faixa("ASSINATURAS", w)]
        if resumo["resultado"] != 0:
            linhas += ["Justificativa da diferença:", "", "_" * w, "", "_" * w]
        linhas += ["", "", "_" * w, f"Caixa responsável: {quem}".strip().center(w)[:w], "", "", "_" * w,
                   "Gerente / quem recebe o caixa".center(w)]
        return linhas

    def comprovante_movimento(self, tipo: str, valor_cent: int, descricao: str, operador: str) -> str:
        w = self.largura()
        titulo = "SANGRIA" if tipo == "saida" else "ENTRADA DE CAIXA"
        return "\n".join(self.cabecalho(w) + _titulo(titulo, w) + [
            _lr("Data:", fmt.fmt_datahora(fmt.agora())[:16], w), _lr("Operador:", operador or "", w), "-" * w,
            _lr("Valor", f"R$ {M(valor_cent)}", w), "-" * w, f"Motivo: {descricao}"[:w * 2], "", "", "_" * w,
            "Assinatura".center(w), "=" * w])

    def comprovante_saida(self, info: dict, operador: str) -> str:
        """Ticket de saída do código 1002: o cliente que não consumiu entrega este papel na porta. Só o nome da casa no topo,
        o aviso em destaque, data e hora, quem liberou, o nº do ticket e a comanda (ou mesa) liberada."""
        w = self.largura()
        l = self.config.loja()
        fantasia, razao = (l["nome_fantasia"] or "").strip(), (l["razao_social"] or "").strip()
        casa = [n.upper()[:w].center(w) for n in dict.fromkeys(x for x in (fantasia or razao or "PDV", razao) if x)]
        quando = fmt.fmt_datahora(info["quando"])                       # dd/mm/aaaa hh:mm:ss
        tipo = "CARTAO" if info.get("comanda", True) else "MESA"
        posicao = info.get("rotulo") or str(info.get("numero", ""))
        numero = f"{info['ticket']:06d}" if info.get("ticket") else ""
        direita = f"CUPOM: {info['cupom']}" if info.get("cupom") else (f"TICKET: {numero}" if numero else "")
        linhas = ["=" * w, "TICKET DE SAIDA".center(w), "=" * w, *casa, "=" * w,
                  *(["FAVOR ENTREGAR ESTE TICKET NA SAIDA".center(w)] if w >= 35       # fita de 58mm: em duas linhas
                    else ["FAVOR ENTREGAR ESTE".center(w), "TICKET NA SAIDA".center(w)]), "=" * w,
                  _lr(f"DATA: {quando[:10]}", f"HORA: {quando[11:19]}", w), "-" * w,
                  _lr(f"OPERADOR: {operador or ''}", direita, w),
                  f"POSICAO DE ORIGEM: {posicao}"[:w], "-" * w,
                  f"{tipo}: {posicao}  {'PAGO - LIBERADO' if info.get('cupom') else 'LIBERADO'}"[:w], "=" * w]
        return "\n".join(linhas)

    def saida_da_venda(self, venda_id: int) -> str | None:
        """Ticket de saída da comanda (ou mesa) que acabou de ser paga: sai junto com o cupom para o cliente entregar na
        portaria, sem precisar do código 1002. None se não for comanda/mesa paga ou se a casa desligou
        (imprimir_saida_ao_pagar)."""
        if not self.banco.cfg_bool("imprimir_saida_ao_pagar", True):
            return None
        v = self.caixa.obter(venda_id)
        if v["modalidade"] != "mesa" or v["status"] != "fechada":
            return None
        operador = self.banco.valor("SELECT nome FROM operadores WHERE id = ?", (v["operador_id"],), "")
        info = {"nome": nome_posicao(v["comanda"], v["posicao"]), "rotulo": self.caixa.rotular_posicao(v["comanda"], v["posicao"]),
                "quando": v["fechada_em"], "comanda": bool(v["comanda"]), "numero": v["posicao"], "cupom": v["cupom"]}
        return self.comprovante_saida(info, operador)

    def via_comissao(self, lancamento: dict, nome: str, operador: str) -> str:
        """A via que a garota leva a cada comissão marcada para ela: só o valor DESTE lançamento (não fiscal). O que já estava
        marcado antes saiu na via de cada lançamento anterior; o total a receber aparece no acerto."""
        from src.controllers.comissao_controller import ComissaoController
        comissoes = ComissaoController(self.banco)
        w = self.largura()
        quem = f"{lancamento['garota']} {nome}".strip()
        rotulo = "Pontos desta comissão" if comissoes.em_pontos() else "Valor desta comissão"
        linhas = self.cabecalho(w) + _titulo("COMISSÃO LANÇADA", w) + ["VIA DA GAROTA".center(w), f"Garota: {quem}"[:w],
            _lr(f"Lançamento nº {lancamento['id']}", fmt.fmt_datahora(lancamento["criado_em"])[:16], w),
            "-" * w, _lr(rotulo, comissoes.em_pontos_texto(lancamento["valor_cent"]) if comissoes.em_pontos()
                         else M(lancamento["valor_cent"]), w),
            "-" * w, f"Operador: {operador}", "Guarde esta via para conferir o acerto.".center(w), "=" * w]
        return "\n".join(linhas)

    def imprimir_via_comissao(self, lancamento_id: int, operador: str) -> str | None:
        """Imprime a via da garota para o lançamento recém-marcado. Devolve o caminho do histórico, ou None se a impressão da
        via está desligada. Sem impressora (modo tela) só grava o arquivo, sem abrir janela a cada lançamento."""
        if not self.banco.cfg_bool("imprimir_via_comissao", True):
            return None
        from src.controllers.comissao_controller import ComissaoController
        comissoes = ComissaoController(self.banco)
        lanc = comissoes.lancamento(lancamento_id)
        if lanc is None:
            return None
        texto = self.via_comissao(lanc, comissoes.nome(lanc["garota"]), operador)
        return self.enviar(texto, f"via_comissao_{lanc['garota']}_{lancamento_id}", tipo="via_comissao")

    def recibo_comissao(self, pag: dict, operador: str) -> str:
        """Recibo do acerto da garota (não fiscal): a comissão (quantos lançamentos e o total), os shows que o operador lançou
        (quantidade x valor), o total entregue e a linha da assinatura. Os lançamentos não saem um a um: só a quantidade e o total.
        Sem shows é o recibo de comissão de sempre; sem comissão nem shows é o recibo do fechamento zerado."""
        w = self.largura()
        quem = f"{pag['garota']} {pag['nome']}".strip()
        shows = pag.get("shows", 0)
        comissao = pag.get("comissao_cent", pag["total_cent"] - pag.get("shows_cent", 0))
        so_comissao = bool(pag["quantidade"]) and not shows
        linhas = self.cabecalho(w) + _titulo("RECIBO DE COMISSÃO" if so_comissao else "RECIBO DE ACERTO", w) + [
            f"Garota: {quem}"[:w], _lr("Pago em:", fmt.fmt_datahora(pag["pago_em"])[:16], w), "-" * w]
        if shows:
            linhas += [_lr(f"COMISSÃO ({pag['quantidade']})", M(comissao), w),
                       _lr(f"SHOWS: {shows} x {M(pag['valor_show_cent'])}", M(pag["shows_cent"]), w),
                       "-" * w, _lr("TOTAL PAGO", M(pag["total_cent"]), w)]
        else:
            linhas.append(_lr(f"TOTAL PAGO ({pag['quantidade']})", M(pag["total_cent"]), w))
        pix, vale = pag.get("pix_cent", 0), pag.get("vale_cent", 0)
        if pix or vale:
            dinheiro = pag["total_cent"] - pix - vale
            if dinheiro:
                linhas.append(_lr("Dinheiro" + (" (saiu do caixa)" if pag.get("tirou_do_caixa") else " (fora do caixa)"), M(dinheiro), w))
            if vale:
                linhas.append(_lr("Vale (já recebido)", M(vale), w))
            if pix:
                linhas.append(_lr("Pix", M(pix), w))
        elif not pag["total_cent"]:
            linhas.append("Conta fechada, nada a pagar.")
        else:
            linhas.append("Saiu do dinheiro do caixa." if pag.get("tirou_do_caixa") else "Pago fora do caixa.")
        linhas += [f"Operador: {operador}", "", "", "_" * w, "Assinatura da garota".center(w), "=" * w]
        return "\n".join(linhas)

    def leitura_x(self, turno_id: int) -> str:
        """Parcial gerencial do turno (equivale ao uso da Leitura X do manual; não é fiscal)."""
        from src.controllers.turno_controller import TurnoController
        return "LEITURA X (GERENCIAL - NÃO FISCAL)\n" + self.fechamento(TurnoController(self.banco).resumo(turno_id))

    def reducao_z(self, data_iso: str | None = None) -> str:
        """Fechamento gerencial do dia (não fiscal: não bloqueia vendas nem zera contadores)."""
        d = data_iso or fmt.hoje()
        rel = RelatorioController(self.banco).totalizacao_fita({"de": d, "ate": d})
        rel.titulo = f"Redução Z (gerencial) {fmt.fmt_data(d)}"
        return para_texto(rel, self.largura())

    def tabela_precos(self) -> str:
        """Botão 'Imprimir Tabela' do cadastro de produtos: código, descrição e preço."""
        w = self.largura()
        linhas = ["TABELA DE PREÇOS".center(w), fmt.fmt_datahora(fmt.agora()).center(w), "=" * w]
        from src.controllers.produto_controller import ProdutoController
        prods = ProdutoController(self.banco)
        for p in prods.listar_venda():
            linhas.append(_lr(f"{p['codigo'][-6:]} {p['nome']}", M(prods.preco_vigente(p)), w))
        return "\n".join(linhas)

    # ----------------------------------------------------------- saída
    def pasta_saida(self) -> Path:
        p = RAIZ / "impressao"
        p.mkdir(exist_ok=True)
        return p

    @staticmethod
    def _gravar_unico(pasta: Path, nome: str, texto: str) -> Path:
        """Grava `texto` em pasta/<data-hora>-<nome>.txt SEM sobrescrever: dois documentos com o mesmo nome no mesmo
        segundo (ex.: dois itens do mesmo subgrupo lidos no leitor de código de barras) ganham -2, -3... Na pasta da
        impressora remota o arquivo é o próprio pedido, então sobrescrever perderia um pedido da cozinha."""
        seguro = re.sub(r"[^A-Za-z0-9_-]+", "_", nome)[:40] or "documento"
        base = f"{fmt.agora().replace(':', '').replace(' ', '-')}-{seguro}"
        for n in range(1, 1000):
            caminho = pasta / (f"{base}.txt" if n == 1 else f"{base}-{n}.txt")
            try:
                with open(caminho, "x", encoding="utf-8") as f:
                    f.write(texto)
                return caminho
            except FileExistsError:
                continue
        raise OSError(f"Não foi possível gravar o documento {base} em {pasta}.")

    def _historico(self, texto: str, nome: str) -> str:
        """Grava sempre uma cópia do documento em impressao/ (rastreabilidade)."""
        caminho = self._gravar_unico(self.pasta_saida(), nome, texto)
        return str(caminho)

    def impressora_termica(self) -> ImpressoraTermica:
        return ImpressoraTermica.da_maquina(self.config.maquina())

    def modo(self) -> str:
        return self.config.maquina()["modo_impressao"]

    def deve_mostrar_na_tela(self) -> bool:
        return self.modo() == "tela"

    def _logotipo(self, tipo: str | None) -> bytes | None:
        """Logotipo em ESC/POS para o documento, ou None (desligado, sem arquivo ou arquivo inválido).
        Um logotipo ruim nunca impede o cupom de sair: o erro vai para o log e o cupom sai sem ele."""
        if tipo not in TIPOS_COM_LOGOTIPO:
            return None
        m = self.config.maquina()
        caminho = (self.config.loja().get("logotipo") or "").strip()
        if not m["impressora_termica_logotipo"] or not caminho:
            return None
        try:
            return logotipo_escpos(caminho, int(m["colunas_fita"] or 48))
        except ErroImpressao as e:
            self.banco.log("logotipo_invalido", str(e)[:300])
            return None

    def opcoes_cupom(self, venda_id: int) -> dict:
        """Vias e gaveta de um cupom, a partir das formas de pagamento usadas na venda.

        vias  = maior 'nº de vias' entre as formas (cadastro de tipos de pagamento), de 1 a 3;
        gaveta = alguma forma fica fisicamente na gaveta (dinheiro, cheque, ticket) ou houve troco."""
        r = self.banco.um(
            """SELECT COALESCE(MAX(t.vias), 1) AS vias, COALESCE(MAX(t.na_gaveta), 0) AS na_gaveta
               FROM pagamentos_venda p JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""",
            (venda_id,))
        troco = self.banco.valor("SELECT troco_cent FROM vendas WHERE id = ?", (venda_id,), 0)
        return {"copias": max(1, min(int(r["vias"] or 1), 3)), "abrir_gaveta": bool(r["na_gaveta"]) or troco > 0}

    def enviar(self, texto: str, nome: str = "documento", tipo: str | None = None, abrir_gaveta: bool = False,
               copias: int = 1, venda_id: int | None = None) -> str:
        """Grava o histórico e entrega o documento à saída configurada.

        Na térmica o documento vai para a FILA e este método volta na hora: a thread da fila imprime, tenta de novo
        se a impressora estiver fora e o caixa não espera. Só levanta ErroImpressao para erro de configuração
        (ex.: nenhuma impressora definida). No modo Windows manda o arquivo para a impressora padrão."""
        caminho = self._historico(texto, nome)
        modo = self.modo()
        if modo == "termica":
            imp = self.impressora_termica()
            if not imp.configurada:
                raise ErroImpressao("Nenhuma impressora térmica configurada (Configurações > Máquinas).")
            dados = imp.montar(texto, abrir_gaveta=abrir_gaveta, copias=copias, logotipo=self._logotipo(tipo),
                               **_ESTILOS.get(tipo or "", {"negrito_linhas": 1}))
            self.fila.enfileirar("caixa", nome, dados, tipo, venda_id)
        elif modo == "windows" and hasattr(os, "startfile"):
            for _ in range(max(1, copias)):
                os.startfile(caminho, "print")  # type: ignore[attr-defined]
        return caminho

    def enviar_remoto(self, texto: str, nome: str, setor: dict | None = None) -> str:
        """Pedido para a cozinha/bar: vai para a impressora remota (pasta ou rede), nunca para a do caixa.
        Por rede entra na fila (a cozinha fora do ar não trava o caixa). Também grava no histórico.

        `setor` (Configurações > Módulos > Cozinha/Bar) usa a conexão cadastrada nele em vez da impressora
        remota única da máquina; sem setor (módulo desligado ou subgrupo sem setor), nada muda."""
        caminho = self._historico(texto, nome)
        m = self.config.maquina()
        conexao = ((setor or {}).get("conexao") or m["impressora_remota_conexao"] or "pasta").strip()
        endereco = (setor or {}).get("endereco") or m["impressora_remota_endereco"]
        pasta = (setor or {}).get("pasta") or m["impressora_remota_pasta"]
        if conexao in ("rede", "spooler"):
            if not (endereco or "").strip():
                raise ErroImpressao("Informe o endereço (rede) ou o nome (Windows) da impressora remota "
                                    "(Configurações > Máquinas, ou do setor em Cadastros > Setores de Impressão).")
            dados = term.texto_para_escpos(texto, codepage=m["impressora_termica_codepage"] or "cp850",
                                           cortar=True, negrito_linhas=1)
            self.fila.enfileirar("remota", nome, dados, "pedido", setor_id=(setor or {}).get("id"))
        elif conexao == "pasta":
            pasta = (pasta or "").strip()
            if pasta:
                destino = Path(pasta)
                destino.mkdir(parents=True, exist_ok=True)
                self._gravar_unico(destino, nome, texto)
        return caminho

    # -------------------------------------------------- gaveta / teste / 2ª via
    def abrir_gaveta(self) -> None:
        """Abre a gaveta pelo pulso da impressora térmica."""
        self.impressora_termica().abrir_gaveta()

    def impressora_de(self, conexao: str, endereco: str) -> ImpressoraTermica:
        """A térmica com esta conexão e este endereço e o resto (página de código, colunas, corte) do que está gravado
        na máquina: serve para testar uma escolha da lista de impressoras antes de gravá-la."""
        m = dict(self.config.maquina())
        m["impressora_termica_conexao"], m["impressora_termica_endereco"] = conexao, endereco
        return ImpressoraTermica.da_maquina(m)

    def imprimir_teste(self, impressora: ImpressoraTermica | None = None) -> None:
        """Página de teste da impressora térmica (Configurações > Máquinas). Sem `impressora`, usa a configurada."""
        imp = impressora or self.impressora_termica()
        imp.imprimir(imp.ticket_teste(self.config.nome_loja()), grande_prefixos=("TOTAL",), negrito_linhas=1)

    def reimprimir_cupom(self, venda_id: int) -> str:
        """Segunda via de um cupom já fechado/cancelado. Envia para a saída e devolve o texto."""
        texto = self.cupom(venda_id, segunda_via=True)
        self.enviar(texto, f"2via_cupom_{self.banco.valor('SELECT cupom FROM vendas WHERE id=?', (venda_id,)) or venda_id}",
                    tipo="cupom", venda_id=venda_id)
        return texto
