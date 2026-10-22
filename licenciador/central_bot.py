"""Bot administrativo separado dos bots dos donos, executado no PC fornecedor."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

from licenciador.central import Central, ErroCentral
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.sync.telegram_api import ClienteTelegram, ErroTelegram

log = logging.getLogger("pdv.central")
AJUDA = (
    "Central do fornecedor — sem faturamento das lojas.\n"
    "/lojas [página] — lojas e vencimentos\n"
    "/loja CHAVE — licença emitida, publicada e contato dos caixas\n"
    "/caixas [página] — contatos técnicos recebidos\n"
    "/solicitacoes [página] — pedidos recebidos das lojas\n"
    "/emitir CHAVE MESES — preparar licença mensal (não cobra)\n"
    "/confirmar CÓDIGO — confirmar emissão em até 5 minutos\n"
    "/sincronizar — publicar licenças e consultar a ponte\n"
    "Cadastro de administradores, lojas, aprovação/revogação de caixas e backup "
    "são feitos localmente no computador central."
)


class BotCentral:
    def __init__(self, central: Central, cliente: ClienteTelegram):
        self.central, self.cliente = central, cliente

    @staticmethod
    def _pagina(itens: list[str], argumentos: list[str], titulo: str) -> str:
        if len(argumentos) > 1 or (argumentos and not argumentos[0].isdigit()):
            raise ErroCentral("Informe um número de página positivo.")
        pagina = int(argumentos[0]) if argumentos else 1
        paginas = max(1, (len(itens) + 7) // 8)
        if not 1 <= pagina <= paginas:
            raise ErroCentral(f"Escolha uma página de 1 a {paginas}.")
        return f"{titulo} ({pagina}/{paginas})\n" + ("\n".join(itens[(pagina - 1) * 8:pagina * 8]) or "Nenhum registro.")

    def responder(self, chat_id: int, texto: str) -> str:
        if not self.central.autorizado(chat_id):
            raise ErroCentral("Administrador não autorizado.")
        partes = texto.strip().split()
        if not partes:
            return AJUDA
        comando, args = partes[0].lower().split("@")[0].lstrip("/"), partes[1:]
        if comando in ("start", "ajuda", "menu"):
            return AJUDA
        if comando == "lojas":
            linhas = [f"{l['chave']} — {'ativa' if l['ativa'] else 'desativada'} — "
                      f"emitida até {l['validade'] or 'não emitida'}" for l in self.central.lojas()]
            return self._pagina(linhas, args, "Lojas locais")
        if comando == "caixas":
            linhas = [f"{c['chave_loja']} / {c['caixa_id']}\n"
                      f"Versão: {c.get('versao') or 'não informada'}; "
                      f"contato: {c.get('ultimo_contato') or 'não recebido'}; "
                      f"credencial: {'revogada' if c.get('revogado') else 'ativa'}"
                      for c in self.central.retrato("caixas")]
            return self._pagina(linhas, args, "Caixas — retrato da última consulta")
        if comando == "solicitacoes":
            linhas = [f"{p['chave_loja']} — {p['id']} — {p.get('situacao', 'pendente')}"
                      for p in self.central.retrato("solicitacoes")]
            return self._pagina(linhas, args, "Solicitações — não são autorizações de emissão")
        if comando == "loja":
            if len(args) != 1:
                raise ErroCentral("Use /loja CHAVE.")
            from licenciador.central import chave_loja
            chave = chave_loja(args[0])
            loja = next((l for l in self.central.lojas() if l["chave"].casefold() == chave.casefold()), None)
            if loja is None:
                raise ErroCentral("Loja não cadastrada localmente.")
            chave = loja["chave"]
            emitida = self.central.db.execute(
                "SELECT id,expira_em,publicada FROM licencas WHERE loja=? ORDER BY expira_em DESC LIMIT 1",
                (chave,)).fetchone()
            texto_licenca = ("Nenhuma licença emitida." if emitida is None else
                            f"Emitida até {emitida['expira_em']}; "
                            f"{'publicada na ponte' if emitida['publicada'] else 'publicação pendente'}.")
            caixas = [c for c in self.central.retrato("caixas") if c["chave_loja"] == chave]
            linhas = [f"{c['caixa_id']}: contato {c.get('ultimo_contato') or 'não recebido'}; "
                      f"aplicada {c.get('licenca_aplicada_id') or 'não confirmada'}" for c in caixas[:8]]
            return (f"{chave} — {loja['nome']}\n{texto_licenca}\n" + "\n".join(linhas) +
                    (f"\nMostrando 8 de {len(caixas)} caixas; veja /caixas." if len(caixas) > 8 else "") +
                    f"\nÚltima consulta à ponte: {self.central.config('ultima_sincronizacao') or 'não realizada'}.\n"
                    "Último contato não comprova que o caixa está online agora.")
        if comando == "emitir":
            if len(args) != 2 or not args[1].isdigit():
                raise ErroCentral("Use /emitir CHAVE MESES (1 a 60).")
            confirmacao = self.central.preparar_emissao(chat_id, args[0], int(args[1]))
            return (f"Preparada emissão para {args[0]}, {int(args[1])} mês(es).\n"
                    "Base: maior entre validade atual e hoje. Não confirma nem cobra pagamento.\n"
                    f"Para autorizar em até 5 minutos: /confirmar {confirmacao}")
        if comando == "confirmar":
            if len(args) != 1:
                raise ErroCentral("Use /confirmar CÓDIGO.")
            identificador = self.central.confirmar_emissao(chat_id, args[0])
            return (f"Emissão local registrada: {identificador}.\n"
                    "A publicação será tentada na sincronização; isso ainda não confirma aplicação no caixa.")
        if comando == "sincronizar" and not args:
            self.central.sincronizar()
            return "Ponte consultada e publicações processadas. Consulte /loja CHAVE para ver a aplicação."
        raise ErroCentral("Comando desconhecido. Use /ajuda.")

    def rodada(self, espera: int = 25) -> int:
        offset = int(self.central.config("telegram_offset", "0"))
        atualizacoes = self.cliente.atualizacoes(offset, espera)
        for atualizacao in atualizacoes:
            mensagem = atualizacao.get("message") or {}
            chat = mensagem.get("chat") or {}
            texto = mensagem.get("text")
            chat_id = chat.get("id")
            if chat.get("type") != "private" or type(chat_id) is not int or not isinstance(texto, str):
                self.central.configurar("telegram_offset", str(atualizacao["update_id"] + 1))
                continue
            if not self.central.autorizado(chat_id):
                resposta = (f"Central privada. Seu ID nesta conversa é {chat_id}.\n"
                            "A autorização é cadastrada localmente pelo fornecedor; esta mensagem não libera acesso.")
            else:
                try:
                    resposta = self.responder(chat_id, texto)
                except ErroNegocio as erro:
                    resposta = str(erro)
                except (sqlite3.Error, OSError, ValueError):
                    log.error("Falha local ao processar comando administrativo; consulte banco e configuração.")
                    resposta = "Falha ao processar o comando. Confira a central local; não presuma que a operação concluiu."
            # Escritas idempotentes já estão persistidas antes de confirmar o update.
            self.central.configurar("telegram_offset", str(atualizacao["update_id"] + 1))
            self.cliente.enviar(chat_id, resposta)
        return len(atualizacoes)

    def avisos(self) -> None:
        from datetime import date
        hoje = date.fromisoformat(fmt.hoje())
        vencendo = [l for l in self.central.lojas() if l["ativa"] and l["validade"]
                    and (date.fromisoformat(l["validade"]) - hoje).days <= 7]
        administradores = self.central.db.execute("SELECT chat_id FROM administradores").fetchall()
        for admin in administradores:
            chat_id = admin["chat_id"]
            marca = f"aviso_vencimentos_{chat_id}"
            if vencendo and self.central.config(marca) != hoje.isoformat():
                self.cliente.enviar(chat_id, f"Licenças emitidas vencidas ou vencendo: {len(vencendo)} loja(s).\n"
                                    "Consulte /lojas. O aviso não confirma inadimplência nem aplica bloqueio.")
                self.central.configurar(marca, hoje.isoformat())
            novos = []
            for pedido in self.central.retrato("solicitacoes"):
                if pedido.get("situacao") != "pendente":
                    continue
                marca = f"aviso_pedido_{chat_id}_{pedido['id']}"
                if self.central.config(marca):
                    continue
                novos.append((pedido, marca))
                if len(novos) >= 8:
                    break
            if novos:
                self.cliente.enviar(chat_id, "Pedidos de renovação recebidos:\n" +
                                    "\n".join(f"{p['chave_loja']} — {p['id']}" for p, _ in novos) +
                                    "\nNenhuma cobrança ou emissão automática. Consulte /solicitacoes.")
                for _, marca in novos:
                    self.central.configurar(marca, fmt.agora())


class TravaCentral:
    """Ao contrário do caixa, a central não pode prosseguir se a trava não abrir."""
    def __init__(self, banco: Path):
        self.arquivo = Path(str(banco) + ".servico.lock")
        self.stream = None

    def adquirir(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo = self.arquivo.open("a+b")
        if arquivo.tell() == 0:
            arquivo.write(b"0")
            arquivo.flush()
        arquivo.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            arquivo.close()
            raise ErroCentral("Já existe uma central usando este banco, ou a trava não está disponível.") from None
        self.stream = arquivo

    def liberar(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None


def servir(central: Central, token_bot: str, parar: threading.Event | None = None,
           http=None, notificar=None) -> None:
    if not token_bot.strip():
        raise ErroCentral("Configure o token do bot administrativo.")
    trava = TravaCentral(central.arquivo)
    trava.adquirir()
    parar = parar or threading.Event()
    bot = BotCentral(central, ClienteTelegram(token_bot, http))
    proxima = 0.0
    import time
    try:
        bot.cliente.quem_sou()
        while not parar.is_set():
            if time.monotonic() >= proxima:
                try:
                    central.sincronizar()
                    central.configurar("ultimo_erro", "")
                    if notificar:
                        notificar("Central conectada. Ponte sincronizada.")
                except (ErroNegocio, sqlite3.Error):
                    central.configurar("ultimo_erro", "Falha na sincronização da ponte; publicações ficam pendentes.")
                    if notificar:
                        notificar("Falha na ponte. Publicações pendentes; confira conexão e configuração.")
                    log.warning("Central não conseguiu sincronizar a ponte.")
                proxima = time.monotonic() + 60
            try:
                bot.avisos()
                bot.rodada(25)
            except ErroTelegram as erro:
                log.warning("Telegram administrativo indisponível (código %s).", erro.codigo)
                if notificar:
                    notificar("Telegram indisponível. Confira token, internet e outro consumidor do bot.")
                parar.wait(30 if erro.definitivo or erro.codigo == 409 else 5)
    finally:
        trava.liberar()
