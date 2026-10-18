"""Fila de impressão assíncrona para a impressora térmica do caixa e a da cozinha/bar.

Por que existe: enviar direto para uma impressora de rede fora do ar faz o caixa esperar o tempo
limite da conexão (até 6 s) a cada cupom, e se o operador fecha a janela de erro o cupom se perde.
Aqui o documento (bytes ESC/POS prontos) é gravado no banco em milissegundos e uma thread própria
o envia, tentando de novo com espera crescente enquanto a impressora não responde.

Regras:
  * A ORDEM é preservada por destino: um cupom atrasado nunca sai depois do seguinte.
  * Sem sucesso depois de MAX_TENTATIVAS (cerca de uma hora) o item vira 'erro' e espera o operador
    reenviar ou cancelar; nada é apagado sozinho enquanto estiver pendente ou com erro.
  * Nada aqui emite documento fiscal: são os mesmos textos não fiscais do ImpressaoController.
"""
from __future__ import annotations

import threading
from datetime import timedelta

from src.controllers.config_controller import ConfigController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.hardware import impressora_termica as term
from src.hardware.impressora_termica import ImpressoraTermica

ESPERAS = (5, 10, 20, 40, 60)     # segundos entre tentativas; a última se repete
MAX_TENTATIVAS = 60               # cerca de uma hora a cada minuto, depois vira 'erro'
DESTINOS = ("caixa", "remota")

# Acorda a thread assim que algo entra na fila (senão ela só olha a cada `intervalo` segundos).
_ACORDAR = threading.Event()


def _enviar_padrao(item: dict, maquina: dict) -> None:
    """Envia os bytes do item pela conexão atualmente configurada para o destino dele."""
    if item["destino"] == "remota":
        endereco = (maquina.get("impressora_remota_endereco") or "").strip()
        if (maquina.get("impressora_remota_conexao") or "") == "spooler":
            term.enviar_spooler(endereco, item["dados"], "PDV Pedido")
        else:
            term.enviar_rede(endereco, item["dados"])
    else:
        ImpressoraTermica.da_maquina(maquina).enviar_bytes(item["dados"])


class FilaImpressao:
    def __init__(self, banco, enviador=None):
        self.banco = banco
        self.enviador = enviador or _enviar_padrao

    # ------------------------------------------------------------ gravação
    def enfileirar(self, destino: str, nome: str, dados: bytes, tipo: str | None = None,
                   venda_id: int | None = None) -> int:
        if destino not in DESTINOS:
            raise ErroNegocio(f"Destino de impressão inválido: {destino}")
        if not dados:
            raise ErroNegocio("Nada para imprimir.")
        item_id = self.banco.inserir("fila_impressao", {
            "criado_em": fmt.agora(), "destino": destino, "tipo": tipo, "nome": nome,
            "dados": bytes(dados), "status": "pendente", "venda_id": venda_id})
        _ACORDAR.set()
        return item_id

    # ----------------------------------------------------------- consulta
    def contagem(self) -> dict:
        """Números para o indicador do caixa."""
        r = self.banco.um(
            """SELECT COALESCE(SUM(status = 'pendente'), 0) AS pendentes,
                      COALESCE(SUM(status = 'pendente' AND tentativas > 0), 0) AS falhando,
                      COALESCE(SUM(status = 'erro'), 0) AS erros FROM fila_impressao
               WHERE status IN ('pendente', 'erro')""")
        ultimo = self.banco.valor(
            "SELECT ultimo_erro FROM fila_impressao WHERE status IN ('pendente','erro') AND ultimo_erro IS NOT NULL "
            "ORDER BY id DESC LIMIT 1")
        return {"pendentes": r["pendentes"], "falhando": r["falhando"], "erros": r["erros"], "ultimo_erro": ultimo}

    def texto_indicador(self) -> tuple[str, str]:
        """(texto, nivel) com nivel em 'ok' | 'aviso' | 'erro' para pintar o indicador na tela."""
        c = self.contagem()
        if c["erros"]:
            return f"Impressora: {c['erros']} com erro (reenviar)", "erro"
        if c["falhando"]:
            return f"Impressora fora? {c['pendentes']} na fila", "aviso"
        if c["pendentes"]:
            return f"Imprimindo ({c['pendentes']})", "aviso"
        return "Impressora: ok", "ok"

    def listar(self, limite: int = 200) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT id, criado_em, destino, tipo, nome, status, tentativas, proxima_tentativa, ultimo_erro,
                      enviado_em, venda_id, length(dados) AS bytes
               FROM fila_impressao ORDER BY id DESC LIMIT ?""", (limite,))]

    # ------------------------------------------------------------ envio
    def processar(self, limite: int = 20) -> dict:
        """Tenta enviar o que está pendente e vencido. Devolve {'enviados': n, 'falhas': n}.

        Por destino pega sempre o item MAIS ANTIGO: se ele ainda está esperando a próxima tentativa
        ou falha agora, os seguintes do mesmo destino esperam também (preserva a ordem)."""
        resultado = {"enviados": 0, "falhas": 0}
        maquina = ConfigController(self.banco).maquina()
        for destino in DESTINOS:
            for _ in range(limite):
                agora = fmt.agora()
                item = self.banco.um(
                    "SELECT * FROM fila_impressao WHERE status = 'pendente' AND destino = ? ORDER BY id LIMIT 1",
                    (destino,))
                if item is None or (item["proxima_tentativa"] and item["proxima_tentativa"] > agora):
                    break
                item = dict(item)
                try:
                    self.enviador(item, maquina)
                except Exception as e:  # ErroImpressao, OSError... a thread nunca pode morrer por causa de um item
                    self._falhou(item, str(e))
                    resultado["falhas"] += 1
                    break
                self.banco.executar(
                    "UPDATE fila_impressao SET status = 'enviado', enviado_em = ?, ultimo_erro = NULL, "
                    "tentativas = tentativas + 1 WHERE id = ?", (fmt.agora(), item["id"]))
                resultado["enviados"] += 1
        return resultado

    def _falhou(self, item: dict, erro: str) -> None:
        tentativas = item["tentativas"] + 1
        if tentativas >= MAX_TENTATIVAS:
            self.banco.executar(
                "UPDATE fila_impressao SET status = 'erro', tentativas = ?, ultimo_erro = ?, proxima_tentativa = NULL "
                "WHERE id = ?", (tentativas, erro[:300], item["id"]))
            self.banco.log("impressao_erro", f"{item['nome']}: {erro}"[:500])
            return
        espera = ESPERAS[min(tentativas - 1, len(ESPERAS) - 1)]
        proxima = (fmt.agora_dt() + timedelta(seconds=espera)).strftime("%Y-%m-%d %H:%M:%S")
        self.banco.executar(
            "UPDATE fila_impressao SET tentativas = ?, ultimo_erro = ?, proxima_tentativa = ? WHERE id = ?",
            (tentativas, erro[:300], proxima, item["id"]))

    # --------------------------------------------------- ações do operador
    def reenviar(self, item_id: int) -> None:
        """Tenta agora: serve para item com erro, cancelado ou pendente esperando a próxima tentativa."""
        n = self.banco.executar(
            "UPDATE fila_impressao SET status = 'pendente', tentativas = 0, proxima_tentativa = NULL "
            "WHERE id = ? AND status IN ('pendente','erro','cancelado')", (item_id,)).rowcount
        if not n:
            raise ErroNegocio("Este item já foi impresso.")
        _ACORDAR.set()

    def reenviar_todos(self) -> int:
        """Devolve à fila tudo que está com erro e antecipa o que está esperando."""
        n = self.banco.executar(
            "UPDATE fila_impressao SET status = 'pendente', tentativas = 0, proxima_tentativa = NULL "
            "WHERE status IN ('pendente','erro')").rowcount
        if n:
            _ACORDAR.set()
        return n

    def cancelar(self, item_id: int) -> None:
        n = self.banco.executar(
            "UPDATE fila_impressao SET status = 'cancelado' WHERE id = ? AND status IN ('pendente','erro')",
            (item_id,)).rowcount
        if not n:
            raise ErroNegocio("Só é possível cancelar itens pendentes ou com erro.")

    def limpar_antigos(self, dias: int = 7) -> int:
        """Apaga da fila o que já foi impresso ou cancelado há mais de `dias` dias (0 = tudo que já saiu)."""
        if dias <= 0:
            return self.banco.executar("DELETE FROM fila_impressao WHERE status IN ('enviado','cancelado')").rowcount
        corte = fmt.somar_dias(fmt.hoje(), -dias)
        return self.banco.executar(
            "DELETE FROM fila_impressao WHERE status IN ('enviado','cancelado') AND date(criado_em) < ?",
            (corte,)).rowcount


class ServicoFilaImpressao:
    """Thread de segundo plano que esvazia a fila. Usa conexão própria com o banco (SQLite não
    compartilha conexão entre threads); por isso precisa de banco em arquivo."""

    def __init__(self, caminho_banco: str, intervalo: float = 2.0, enviador=None):
        if caminho_banco == ":memory:":
            raise ErroNegocio("A fila de impressão em segundo plano precisa de banco em arquivo.")
        self.caminho = caminho_banco
        self.intervalo = intervalo
        self.enviador = enviador
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.ultimo_erro: str | None = None

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="fila-impressao", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 8.0) -> None:
        self._parar.set()
        _ACORDAR.set()
        if self._thread:
            self._thread.join(timeout)

    def _laco(self) -> None:
        from src.database.conexao import BancoDados   # import tardio: evita ciclo na carga dos módulos
        try:
            banco = BancoDados(self.caminho, semear=False)
        except Exception as e:  # noqa: BLE001
            self.ultimo_erro = f"fila de impressão não abriu o banco: {e}"
            return
        fila = FilaImpressao(banco, self.enviador)
        ultima_limpeza = 0.0
        try:
            while not self._parar.is_set():
                try:
                    fila.processar()
                    ultima_limpeza += self.intervalo
                    if ultima_limpeza > 3600:
                        fila.limpar_antigos()
                        ultima_limpeza = 0.0
                except Exception as e:  # noqa: BLE001 - a thread não pode morrer
                    self.ultimo_erro = str(e)
                _ACORDAR.wait(self.intervalo)
                _ACORDAR.clear()
        finally:
            banco.fechar()
