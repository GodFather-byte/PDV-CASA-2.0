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


class FilaImpressao:
    def __init__(self, banco, enviador=None):
        self.banco = banco
        self.enviador = enviador or self._enviar_padrao_setor

    def _enviar_padrao_setor(self, item: dict, maquina: dict) -> None:
        """Envia os bytes do item pela conexão configurada para o destino dele. Com `setor_id` (módulo
        Cozinha/Bar), usa a conexão cadastrada no setor em vez da impressora remota única da máquina."""
        if item["destino"] == "remota":
            setor = self.banco.um("SELECT * FROM setores_impressao WHERE id = ?", (item.get("setor_id"),)) \
                if item.get("setor_id") else None
            conexao = (setor["conexao"] if setor else maquina.get("impressora_remota_conexao")) or ""
            endereco = (setor["endereco"] if setor else maquina.get("impressora_remota_endereco")) or ""
            endereco = endereco.strip()
            if conexao == "spooler":
                term.enviar_spooler(endereco, item["dados"], "PDV Pedido")
            else:
                term.enviar_rede(endereco, item["dados"])
        else:
            ImpressoraTermica.da_maquina(maquina).enviar_bytes(item["dados"])

    # ------------------------------------------------------------ gravação
    def enfileirar(self, destino: str, nome: str, dados: bytes, tipo: str | None = None,
                   venda_id: int | None = None, setor_id: int | None = None) -> int:
        if destino not in DESTINOS:
            raise ErroNegocio(f"Destino de impressão inválido: {destino}")
        if not dados:
            raise ErroNegocio("Nada para imprimir.")
        item_id = self.banco.inserir("fila_impressao", {
            "criado_em": fmt.agora(), "destino": destino, "tipo": tipo, "nome": nome,
            "dados": bytes(dados), "status": "pendente", "venda_id": venda_id, "setor_id": setor_id})
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
        incertos = self.banco.valor("SELECT COUNT(*) FROM fila_impressao WHERE status = 'incerto'", padrao=0)
        if incertos:
            return f"Impressora: {incertos} envio(s) interrompido(s); confira o papel", "erro"
        enviando = self.banco.valor("SELECT COUNT(*) FROM fila_impressao WHERE status = 'enviando'", padrao=0)
        if enviando:
            return f"Impressora: {enviando} documento(s) em envio", "aviso"
        c = self.contagem()
        if c["erros"]:
            return f"Impressora: {c['erros']} com erro (reenviar)", "erro"
        if c["falhando"]:
            return f"Impressora fora? {c['pendentes']} na fila", "aviso"
        if c["pendentes"]:
            return f"Imprimindo ({c['pendentes']})", "aviso"
        return "Impressora: sem pendências (confira o papel)", "ok"

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
                    "SELECT * FROM fila_impressao WHERE status IN ('pendente','enviando','incerto') "
                    "AND destino = ? ORDER BY id LIMIT 1",
                    (destino,))
                if (item is None or item["status"] != "pendente"
                        or (item["proxima_tentativa"] and item["proxima_tentativa"] > agora)):
                    break
                item = dict(item)
                if self.banco.conexao.in_transaction:
                    raise ErroNegocio("Não envie impressão dentro de uma transação de venda.")
                reservado = self.banco.executar(
                    "UPDATE fila_impressao SET status = 'enviando' WHERE id = ? AND status = 'pendente'",
                    (item["id"],)).rowcount
                if not reservado:
                    break
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

    def recuperar_interrompidos(self) -> int:
        """Só no início do serviço, com instância única: o papel pode ter saído antes da interrupção."""
        quantidade = self.banco.executar(
            "UPDATE fila_impressao SET status = 'incerto', proxima_tentativa = NULL, "
            "ultimo_erro = ? WHERE status = 'enviando'",
            ("Envio interrompido. Confira fisicamente o papel antes de confirmar ou reenviar.",)).rowcount
        if quantidade:
            self.banco.log("impressao_interrompida", f"{quantidade} documento(s) exigem conferência física.")
        return quantidade

    def conferir_interrompido(self, item_id: int, *, impresso: bool, operador_id: int) -> None:
        """Decisão humana explícita; um envio incerto nunca entra no reenvio em lote."""
        if type(impresso) is not bool:
            raise ErroNegocio("Informe se o documento saiu fisicamente.")
        from src.controllers.acesso_controller import AcessoController
        cadastro = self.banco.um("SELECT ativo FROM operadores WHERE id = ?", (operador_id,))
        if cadastro is None or not cadastro["ativo"]:
            raise ErroNegocio("Operador inativo ou inexistente.")
        acesso = AcessoController(self.banco)
        acesso.exigir(acesso.operador(operador_id), "util_fila_impressao")
        with self.banco.transacao():
            quantidade = self.banco.executar(
                "UPDATE fila_impressao SET status = ?, enviado_em = ?, ultimo_erro = NULL, "
                "tentativas = 0, proxima_tentativa = NULL WHERE id = ? AND status = 'incerto'",
                ("enviado" if impresso else "pendente", fmt.agora() if impresso else None, item_id)).rowcount
            if not quantidade:
                raise ErroNegocio("Selecione um envio interrompido que ainda aguarda conferência.")
            self.banco.log("impressao_conferida",
                           f"documento {item_id}: " + ("papel confirmado" if impresso else "reenvio autorizado"),
                           operador_id)
        if not impresso:
            _ACORDAR.set()

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
            "UPDATE fila_impressao SET status = 'pendente', tentativas = ?, ultimo_erro = ?, "
            "proxima_tentativa = ? WHERE id = ?",
            (tentativas, erro[:300], proxima, item["id"]))

    # --------------------------------------------------- ações do operador
    def reenviar(self, item_id: int) -> None:
        """Tenta agora: serve para item com erro, cancelado ou pendente esperando a próxima tentativa."""
        n = self.banco.executar(
            "UPDATE fila_impressao SET status = 'pendente', tentativas = 0, proxima_tentativa = NULL "
            "WHERE id = ? AND status IN ('pendente','erro','cancelado')", (item_id,)).rowcount
        if not n:
            raise ErroNegocio("Este item não pode ser reenviado. Se interrompido, use a conferência do papel.")
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
            fila.recuperar_interrompidos()
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
        except Exception as erro:
            self.ultimo_erro = f"Falha ao recuperar a fila de impressão: {erro}"
        finally:
            banco.fechar()
