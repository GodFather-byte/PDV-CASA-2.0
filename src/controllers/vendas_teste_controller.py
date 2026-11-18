"""Apagar vendas de teste (no caixa e, pelo painel, na nuvem), autorizado pela senha de segurança do dono.

Regras:
- A senha de segurança é do dono, separada das senhas de entrada; só o hash fica em `seguranca_dono` (fora de `config`,
  que a retaguarda espelha e altera pela nuvem). Criar ou trocar exige gerente; trocar exige a senha atual. O hash sobe
  para a nuvem no envio do painel, para o dono apagar também por lá.
- Cinco senhas erradas seguidas bloqueiam a exclusão por 15 minutos (aqui e no painel, cada um com o seu contador).
- Só venda fechada ou cancelada. Não apaga: venda com NFC-e (a nota é documento fiscal: cancele ou inutilize), com
  devolução ou troca, com fiado na caderneta, com Pix aprovado (dinheiro de verdade).
- Venda de turno já fechado só com confirmação explícita (o fechamento conferido muda).
- Venda fechada devolve o estoque (como no cancelamento); a cancelada já devolveu.
- O que foi apagado fica em `vendas_apagadas` (registro permanente) e na auditoria, e sobe para a nuvem, que apaga lá.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.core import formatacao as fmt
from src.core import seguranca
from src.core.erros import ErroNegocio, ErroPermissao

TENTATIVAS_MAXIMAS = 5
BLOQUEIO_MINUTOS = 15
SENHA_MINIMA = 6
LIMITE_POR_VEZ = 500
NIVEL_GERENTE = 4


class TurnoFechado(ErroNegocio):
    """Há vendas de turno já fechado: a tela pergunta e chama de novo com confirmar_turno_fechado=True."""

    def __init__(self, turnos: list[int]):
        self.turnos = turnos
        super().__init__("Há vendas de turno já fechado (" + ", ".join(map(str, turnos)) + "). Apagar muda o "
                         "fechamento conferido desses turnos. Confirme para continuar.")


class VendasTesteController:
    def __init__(self, banco, operador_id: int | None = None, estoque=None):
        self.banco = banco
        self.operador_id = operador_id
        if estoque is None:
            from src.controllers.estoque_controller import EstoqueController
            estoque = EstoqueController(banco, operador_id)
        self.estoque = estoque

    # ------------------------------------------------------------ senha de segurança
    def _registro(self):
        return self.banco.um("SELECT * FROM seguranca_dono WHERE id = 1")

    def senha_configurada(self) -> bool:
        return self._registro() is not None

    def _exigir_gerente(self) -> None:
        linha = self.banco.um("SELECT nivel FROM operadores WHERE id = ? AND ativo = 1", (self.operador_id,)) \
            if type(self.operador_id) is int else None
        if linha is None or linha["nivel"] < NIVEL_GERENTE:
            raise ErroPermissao("Somente gerente (nível 4) pode mexer na senha de segurança ou apagar vendas.")

    def definir_senha(self, nova: str, confirmacao: str, atual: str = "") -> None:
        self._exigir_gerente()
        nova = (nova or "").strip()
        if len(nova) < SENHA_MINIMA:
            raise ErroNegocio(f"A senha de segurança precisa ter pelo menos {SENHA_MINIMA} caracteres.")
        if not seguranca.mesma_senha(nova, confirmacao or ""):
            raise ErroNegocio("A confirmação não confere com a senha nova.")
        registro = self._registro()
        if registro is not None:
            self._conferir(atual)                     # trocar exige a atual (e conta tentativa errada)
        hash_ = seguranca.gerar_hash(nova)
        with self.banco.transacao():
            self.banco.executar(
                "INSERT INTO seguranca_dono(id, senha_hash, atualizada_em, tentativas, bloqueada_ate, enviada_em) "
                "VALUES (1, ?, ?, 0, NULL, NULL) ON CONFLICT(id) DO UPDATE SET senha_hash = excluded.senha_hash, "
                "atualizada_em = excluded.atualizada_em, tentativas = 0, bloqueada_ate = NULL, enviada_em = NULL",
                (hash_, fmt.agora()))
            self.banco.registrar_auditoria("seguranca_dono", "1", "trocada" if registro else "criada",
                                           operador_id=self.operador_id)

    def _conferir(self, senha: str) -> None:
        registro = self._registro()
        if registro is None:
            raise ErroNegocio("Crie antes a senha de segurança do dono (Utilitários > Senha de segurança do dono).")
        agora = fmt.agora()
        if registro["bloqueada_ate"] and registro["bloqueada_ate"] > agora:
            raise ErroPermissao(f"Senha de segurança bloqueada por excesso de erros até "
                                f"{fmt.fmt_datahora(registro['bloqueada_ate'])}.")
        if seguranca.conferir(senha or "", registro["senha_hash"]):
            if registro["tentativas"]:
                self.banco.executar("UPDATE seguranca_dono SET tentativas = 0, bloqueada_ate = NULL WHERE id = 1")
            return
        tentativas = int(registro["tentativas"] or 0) + 1
        bloqueio = None
        if tentativas >= TENTATIVAS_MAXIMAS:
            bloqueio = (datetime.strptime(agora, "%Y-%m-%d %H:%M:%S")
                        + timedelta(minutes=BLOQUEIO_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
            tentativas = 0
        self.banco.executar("UPDATE seguranca_dono SET tentativas = ?, bloqueada_ate = ? WHERE id = 1",
                            (tentativas, bloqueio))
        self.banco.log("senha_seguranca_errada", "bloqueada" if bloqueio else f"tentativa {tentativas}",
                       self.operador_id)
        if bloqueio:
            raise ErroPermissao(f"Senha de segurança errada {TENTATIVAS_MAXIMAS} vezes: bloqueada por "
                                f"{BLOQUEIO_MINUTOS} minutos.")
        raise ErroPermissao(f"Senha de segurança incorreta ({TENTATIVAS_MAXIMAS - tentativas} tentativa(s) antes "
                            "do bloqueio).")

    # ------------------------------------------------------------ o que pode ser apagado
    def motivo_bloqueio(self, venda) -> str | None:
        """Por que esta venda não pode ser apagada (None = pode)."""
        vid = venda["id"]
        if venda["status"] not in ("fechada", "cancelada"):
            return "venda ainda aberta (cancele pelo caixa)"
        nota = self.banco.um("SELECT situacao FROM nfce_notas WHERE venda_id = ?", (vid,))
        if nota is not None and nota["situacao"] != "erro":
            return "tem NFC-e (documento fiscal: cancele ou inutilize a nota)"
        if self.banco.um("SELECT 1 FROM devolucoes WHERE venda_id = ? LIMIT 1", (vid,)) \
                or self.banco.um("SELECT 1 FROM devolucoes_trocas WHERE venda_id = ? LIMIT 1", (vid,)):
            return "tem devolução ou troca registrada"
        if self.banco.um("SELECT 1 FROM caderneta WHERE venda_id = ? LIMIT 1", (vid,)):
            return "tem fiado na caderneta"
        if self.banco.um("SELECT 1 FROM pix_cobrancas WHERE venda_id = ? AND situacao = 'aprovado' LIMIT 1", (vid,)):
            return "tem Pix recebido"
        return None

    def candidatas(self, inicio: str, fim: str) -> list[dict]:
        """Vendas fechadas ou canceladas entre as datas (AAAA-MM-DD, inclusive), com o motivo de bloqueio se houver."""
        linhas = self.banco.todos(
            """SELECT v.id, v.uuid, v.cupom, v.status, v.total_cent, v.fechada_em, v.turno_id, v.modalidade,
                      t.fechado_em AS turno_fechado_em
               FROM vendas v LEFT JOIN turnos t ON t.id = v.turno_id
               WHERE v.status IN ('fechada', 'cancelada') AND substr(COALESCE(v.fechada_em, v.aberta_em), 1, 10)
                     BETWEEN ? AND ? ORDER BY COALESCE(v.fechada_em, v.aberta_em), v.id LIMIT ?""",
            (inicio, fim, LIMITE_POR_VEZ * 2))
        saida = []
        for l in linhas:
            d = dict(l)
            d["bloqueio"] = self.motivo_bloqueio(d)
            d["turno_fechado"] = bool(d.pop("turno_fechado_em"))
            saida.append(d)
        return saida

    # ------------------------------------------------------------ apagar
    def apagar(self, venda_ids: list[int], senha: str, confirmar_turno_fechado: bool = False) -> dict:
        """Apaga as vendas escolhidas no caixa, com a senha de segurança. Tudo ou nada."""
        self._exigir_gerente()
        if not venda_ids:
            raise ErroNegocio("Escolha as vendas de teste para apagar.")
        if len(venda_ids) > LIMITE_POR_VEZ:
            raise ErroNegocio(f"Apague no máximo {LIMITE_POR_VEZ} vendas por vez.")
        self._conferir(senha)
        vendas = []
        for vid in dict.fromkeys(int(v) for v in venda_ids):
            v = self.banco.um("""SELECT v.*, t.fechado_em AS turno_fechado_em FROM vendas v
                                 LEFT JOIN turnos t ON t.id = v.turno_id WHERE v.id = ?""", (vid,))
            if v is None:
                raise ErroNegocio(f"Venda {vid} não encontrada.")
            motivo = self.motivo_bloqueio(v)
            if motivo:
                raise ErroNegocio(f"O cupom {v['cupom'] or vid} não pode ser apagado: {motivo}.")
            vendas.append(v)
        fechados = sorted({v["turno_id"] for v in vendas if v["turno_fechado_em"]})
        if fechados and not confirmar_turno_fechado:
            raise TurnoFechado(fechados)
        with self.banco.transacao():
            for v in vendas:
                self._revalidar(v)                        # nada mudou entre a conferência e a exclusão
                self._apagar_uma(v, "caixa")
        total = sum(int(v["total_cent"] or 0) for v in vendas if v["status"] == "fechada")
        self.banco.log("vendas_teste_apagadas", f"{len(vendas)} venda(s), R$ {total / 100:.2f}", self.operador_id)
        return {"apagadas": len(vendas), "total_cent": total}

    def aplicar_da_nuvem(self, uuids: list[str]) -> dict:
        """O dono apagou pelo painel (a nuvem já conferiu a senha de segurança): apaga aqui, com as mesmas travas.
        Venda bloqueada fica e o motivo sobe para o painel; venda que não está neste caixa fica para o caixa dela."""
        feitas, recusadas = [], []
        for uuid in dict.fromkeys(u for u in uuids if isinstance(u, str) and u):
            if self.banco.um("SELECT 1 FROM vendas_apagadas WHERE uuid = ?", (uuid,)) \
                    or self.banco.um("SELECT 1 FROM vendas_apagar_recusadas WHERE uuid = ?", (uuid,)):
                continue
            v = self.banco.um("SELECT * FROM vendas WHERE uuid = ?", (uuid,))
            if v is None:
                continue
            motivo = self.motivo_bloqueio(v)
            if motivo:
                self.banco.executar("INSERT OR IGNORE INTO vendas_apagar_recusadas(uuid, motivo, recusada_em) "
                                    "VALUES (?, ?, ?)", (uuid, motivo, fmt.agora()))
                self.banco.log("vendas_teste_recusada", f"cupom {v['cupom']}: {motivo}", None)
                recusadas.append(uuid)
                continue
            try:
                with self.banco.transacao():
                    self._revalidar(v)
                    self._apagar_uma(v, "painel")
            except ErroNegocio:
                continue                                  # mudou agora (ex.: NFC-e emitida); a próxima rodada confere
            feitas.append(uuid)
        if feitas:
            self.banco.log("vendas_teste_apagadas", f"{len(feitas)} venda(s) pelo painel do dono", None)
        return {"apagadas": feitas, "recusadas": recusadas}

    def _revalidar(self, v) -> None:
        atual = self.banco.um("SELECT * FROM vendas WHERE id = ?", (v["id"],))
        motivo = "não existe mais" if atual is None or atual["uuid"] != v["uuid"] else self.motivo_bloqueio(atual)
        if motivo is None and atual["status"] != v["status"]:
            motivo = "mudou de situação"
        if motivo:
            raise ErroNegocio(f"O cupom {v['cupom'] or v['id']} não pode ser apagado: {motivo}.")

    def _apagar_uma(self, v, origem: str) -> None:
        vid = v["id"]
        if v["status"] == "fechada":
            self.estoque.estornar_venda(vid)              # idempotente; devolve o que a venda baixou
        antes = {"cupom": v["cupom"], "status": v["status"], "total_cent": v["total_cent"],
                 "fechada_em": v["fechada_em"], "turno_id": v["turno_id"]}
        for tabela in ("fila_impressao", "repiques", "quartos_vendas", "pix_cobrancas", "pedidos_mesa_importados",
                       "nfce_notas"):
            self.banco.executar(f"DELETE FROM {tabela} WHERE venda_id = ?", (vid,))
        self.banco.executar("DELETE FROM pagamentos_venda WHERE venda_id = ?", (vid,))
        self.banco.executar("DELETE FROM itens_venda WHERE venda_id = ?", (vid,))
        self.banco.executar("DELETE FROM vendas WHERE id = ?", (vid,))
        self.banco.executar(
            "INSERT OR IGNORE INTO vendas_apagadas(uuid, cupom, status, total_cent, fechada_em, turno_id, origem, "
            "operador_id, apagada_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["uuid"], v["cupom"], v["status"], int(v["total_cent"] or 0), v["fechada_em"], v["turno_id"], origem,
             self.operador_id, fmt.agora()))
        self.banco.registrar_auditoria("venda", v["uuid"], "apagada_como_teste", antes=antes,
                                       depois={"origem": origem}, operador_id=self.operador_id)

    def apagadas(self, limite: int = 200) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM vendas_apagadas ORDER BY id DESC LIMIT ?", (limite,))]


# ------------------------------------------------------------ envio para a nuvem (painel_envio)
def recusadas_envio(banco, limite: int = 200) -> list[dict]:
    return [{"uuid": r["uuid"], "motivo": r["motivo"]} for r in banco.todos(
        "SELECT uuid, motivo FROM vendas_apagar_recusadas WHERE enviada_em IS NULL ORDER BY recusada_em LIMIT ?",
        (limite,))]


def pendentes_envio(banco, limite: int = 200) -> list[dict]:
    return [{"uuid": r["uuid"], "apagada_em": r["apagada_em"], "origem": r["origem"]} for r in banco.todos(
        "SELECT uuid, apagada_em, origem FROM vendas_apagadas WHERE enviada_em IS NULL ORDER BY id LIMIT ?",
        (limite,))]


def hash_para_enviar(banco) -> str | None:
    linha = banco.um("SELECT senha_hash FROM seguranca_dono WHERE id = 1 AND enviada_em IS NULL")
    return linha["senha_hash"] if linha else None


def anotar_resposta(banco, resposta: dict, enviado_hash: str | None) -> None:
    """Confirmações da nuvem: exclusões que ela aplicou, o hash da senha que guardou e exclusões pedidas pelo painel."""
    agora = fmt.agora()
    for uuid in resposta.get("apagadas_uuids") or []:
        if isinstance(uuid, str):
            banco.executar("UPDATE vendas_apagadas SET enviada_em = ? WHERE uuid = ? AND enviada_em IS NULL",
                           (agora, uuid))
    for uuid in resposta.get("recusadas_uuids") or []:
        if isinstance(uuid, str):
            banco.executar("UPDATE vendas_apagar_recusadas SET enviada_em = ? WHERE uuid = ? AND enviada_em IS NULL",
                           (agora, uuid))
    if enviado_hash and resposta.get("seguranca_ok"):
        banco.executar("UPDATE seguranca_dono SET enviada_em = ? WHERE id = 1 AND senha_hash = ?", (agora, enviado_hash))
    pedidos = [u for u in (resposta.get("apagar_no_caixa") or []) if isinstance(u, str)]
    if pedidos:
        VendasTesteController(banco).aplicar_da_nuvem(pedidos[:LIMITE_POR_VEZ])
