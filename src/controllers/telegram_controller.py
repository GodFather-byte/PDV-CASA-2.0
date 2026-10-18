"""Telegram do dono: pareamento, envio dos avisos e respostas aos botões do bot.

Como funciona (tudo parte do PDV, nada entra nele):
  1. O dono cria um bot no @BotFather (2 minutos) e cola o token em Configurações > Telegram.
  2. O PDV mostra um código de 6 dígitos; o dono manda `/start CÓDIGO` ao bot. Só quem digita o código certo (válido por
     10 minutos, no máximo 5 tentativas) fica autorizado: qualquer outra conversa recebe só "bot privado".
  3. Daí em diante o PDV manda os avisos (caixa, cancelamentos, sangrias, resumo da noite) e responde aos botões
     (Resumo, Caixa, Estoque...). O celular não conversa com o PDV: ele pergunta ao Telegram, e o PDV, que fica
     perguntando ao Telegram "tem mensagem nova?", responde. Não abre porta no computador do caixa.
Sem internet o PDV segue vendendo normalmente; os avisos ficam na fila e saem quando a conexão voltar.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
from datetime import timedelta

from src.controllers import notificacoes, telegram_textos as textos
from src.controllers.relatorio_vendas import virada_dia
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.sync.telegram_api import ClienteTelegram, ErroTelegram

log = logging.getLogger("pdv.telegram")

CODIGO_VALIDADE_MIN = 10
CODIGO_MAX_ERROS = 5
FILA_VALIDADE_HORAS = 48          # aviso mais velho que isto não é mais notícia: vira 'erro' em vez de chegar atrasado
ESPERAS = (5, 10, 20, 40, 60)     # segundos entre tentativas quando o Telegram não responde; a última se repete

# Os botões do teclado do bot: (texto do botão, comando interno). Quem digitar "/resumo" ou "resumo" também funciona.
BOTOES = [("📊 Resumo", "resumo"), ("📅 Ontem", "ontem"), ("💵 Caixa", "caixa"), ("🍺 Mais vendidos", "top"),
          ("📦 Estoque", "estoque"), ("🛒 Comprar", "comprar"), ("🪑 Abertas", "abertas"), ("❌ Cancelamentos", "cancelamentos"),
          ("📈 Semana", "semana"), ("🗓️ Mês", "mes"), ("🕐 Por hora", "horas"), ("👥 Equipe", "equipe"),
          ("💳 Contas", "contas"), ("📒 Caderneta", "caderneta"), ("🔎 Produto", "produto")]
TECLADO = [[BOTOES[i][0], BOTOES[i + 1][0]] for i in range(0, len(BOTOES) - 1, 2)] + [[BOTOES[-1][0]]]
_COMANDOS = {texto: cmd for texto, cmd in BOTOES}
_COMANDOS.update({cmd: cmd for _, cmd in BOTOES})
_COMANDOS.update({"mais vendidos": "top", "cancelamentos": "cancelamentos", "ajuda": "ajuda", "help": "ajuda", "menu": "ajuda",
                  "mês": "mes", "por hora": "horas", "hora": "horas", "compras": "comprar", "lista de compras": "comprar",
                  "vendas da semana": "semana", "semanal": "semana", "mensal": "mes", "garçons": "equipe", "garcons": "equipe",
                  "devedores": "caderneta", "mesas": "abertas", "produtos": "produto", "mesa": "mesa", "comanda": "mesa"})
# Comandos que levam um argumento depois do nome: "produto skol", "mesa 12", "comanda 5".
_COM_ARGUMENTO = {"produto": "produto", "produtos": "produto", "preço": "produto", "preco": "produto", "buscar": "produto",
                  "mesa": "mesa", "comanda": "comanda"}


def normalizar_comando(texto: str) -> str | None:
    """'/resumo@MeuBot', '📊 Resumo', 'resumo' -> 'resumo'; o que não for comando devolve None."""
    t = (texto or "").strip()
    if t in _COMANDOS:
        return _COMANDOS[t]
    t = re.sub(r"@\w+$", "", t.split()[0] if t.startswith("/") else t).lstrip("/").lower().strip()
    return _COMANDOS.get(t)


def interpretar(texto: str) -> tuple[str, str] | None:
    """Entende o que o dono mandou: (comando, argumento) ou None. 'produto skol' -> ('produto', 'skol'); 'mesa 12' ->
    ('mesa', 'M12'); 'comanda 5' -> ('mesa', 'C5'); 'resumo' -> ('resumo', '')."""
    t = (texto or "").strip()
    partes = t.lstrip("/").split(None, 1)
    if len(partes) == 2:
        primeira = re.sub(r"@\w+$", "", partes[0]).lower()
        arg = partes[1].strip()
        if _COM_ARGUMENTO.get(primeira) == "produto":
            return "produto", arg
        if _COM_ARGUMENTO.get(primeira) in ("mesa", "comanda") and re.fullmatch(r"\d{1,4}", arg):
            return "mesa", ("M" if _COM_ARGUMENTO[primeira] == "mesa" else "C") + arg
    simples = normalizar_comando(t)
    return (simples, "") if simples else None


class TelegramController:
    def __init__(self, banco, http=None):
        self.banco = banco
        self._http = http          # nos testes, um falso: http(url, dados, timeout) -> dict

    # ------------------------------------------------------------ cliente
    @property
    def token(self) -> str:
        return self.banco.cfg("telegram_token").strip()

    def cliente(self, token: str | None = None) -> ClienteTelegram:
        """Cria um cliente HTTP independente do banco, inclusive para validar outro token."""
        return ClienteTelegram(self.token if token is None else token, self._http)

    def ligado(self) -> bool:
        return self.banco.cfg_bool("telegram_ativo", False) and bool(self.token)

    def ultimo_erro(self) -> str:
        return self.banco.cfg("telegram_erro")

    def _erro(self, mensagem: str) -> None:
        if self.banco.cfg("telegram_erro") != mensagem:       # só grava quando muda (evita escrever a cada tentativa)
            self.banco.cfg_set("telegram_erro", mensagem)

    # -------------------------------------------------------------- token
    def salvar_token(self, token: str) -> dict:
        """Confere o token no Telegram e, se for válido, guarda. Devolve os dados do bot (inclui 'username')."""
        token = (token or "").strip()
        if not re.fullmatch(r"\d{5,}:[\w-]{20,}", token):
            raise ErroNegocio("Esse token não parece certo. Ele é como 123456789:ABCdefGhIJK... (copie inteiro do @BotFather).")
        try:
            bot = self.cliente(token).quem_sou()
        except ErroTelegram as e:
            raise ErroNegocio("O Telegram não aceitou esse token: confira se copiou inteiro."
                              if e.codigo in (401, 404) else str(e)) from None
        return self.salvar_token_validado(token, bot)

    def salvar_token_validado(self, token: str, bot: dict) -> dict:
        """Persiste o token e os dados devolvidos por getMe já confirmado pelo chamador.

        Não faz rede. Permite validar fora da thread do banco mantendo a mesma
        persistência usada por salvar_token e pela interface Tk.
        """
        token = (token or "").strip()
        if token != self.token:                                 # outro bot: os pareamentos do anterior não valem
            self.banco.executar("DELETE FROM telegram_chats")
            self.banco.cfg_set("telegram_offset", "0")
        self.banco.cfg_set("telegram_token", token)
        self.banco.cfg_set("telegram_bot_usuario", bot.get("username") or "")
        self._erro("")
        return bot

    def bot_usuario(self) -> str:
        return self.banco.cfg("telegram_bot_usuario")

    # ---------------------------------------------------------- pareamento
    def gerar_codigo(self) -> str:
        if not self.token:
            raise ErroNegocio("Cole primeiro o token do bot.")
        codigo = f"{secrets.randbelow(10 ** 6):06d}"
        ate = (fmt.agora_dt() + timedelta(minutes=CODIGO_VALIDADE_MIN)).strftime("%Y-%m-%d %H:%M:%S")
        self.banco.cfg_set("telegram_codigo", codigo)
        self.banco.cfg_set("telegram_codigo_ate", ate)
        self.banco.cfg_set("telegram_codigo_erros", "0")
        return codigo

    def codigo_pendente(self) -> str | None:
        codigo, ate = self.banco.cfg("telegram_codigo"), self.banco.cfg("telegram_codigo_ate")
        return codigo if codigo and ate > fmt.agora() else None

    def _conferir_codigo(self, tentado: str) -> bool:
        """Compara o código digitado com o gerado. Errou demais: o código é descartado (precisa gerar outro)."""
        codigo = self.codigo_pendente()
        if not codigo:
            return False
        if secrets.compare_digest(tentado.strip(), codigo):
            self.banco.cfg_set("telegram_codigo", "")
            return True
        erros = self.banco.cfg_int("telegram_codigo_erros", 0) + 1
        self.banco.cfg_set("telegram_codigo_erros", erros)
        if erros >= CODIGO_MAX_ERROS:
            self.banco.cfg_set("telegram_codigo", "")
        return False

    def chats(self) -> list[dict]:
        return [dict(r) for r in self.banco.todos("SELECT * FROM telegram_chats ORDER BY criado_em")]

    def remover_chat(self, chat_id: int) -> None:
        self.banco.executar("DELETE FROM telegram_chats WHERE chat_id = ?", (chat_id,))
        self.banco.log("telegram_removido", f"chat {chat_id}")

    def _parear(self, chat_id: int, nome: str) -> None:
        self.banco.executar("INSERT OR REPLACE INTO telegram_chats(chat_id, nome, criado_em) VALUES (?,?,?)",
                            (chat_id, nome, fmt.agora()))
        self.banco.cfg_set("telegram_ativo", "S")
        if not self.banco.cfg("telegram_ultimo_resumo"):      # o primeiro resumo automático é o da próxima manhã
            self.banco.cfg_set("telegram_ultimo_resumo", textos.dia_anterior(self.banco))
        self.banco.log("telegram_pareado", f"chat {chat_id} {nome}")

    # ------------------------------------------------------------- envio
    def enviar_a_todos(self, texto: str, teclado=None) -> int:
        """Envia direto (sem fila) a todos os celulares pareados. Devolve quantos receberam; levanta ErroTelegram."""
        enviados = 0
        for chat in self.chats():
            self.cliente().enviar(chat["chat_id"], texto, teclado)
            enviados += 1
        return enviados

    def testar(self) -> int:
        """Botão 'Enviar mensagem de teste' da tela."""
        if not self.chats():
            raise ErroNegocio("Nenhum celular pareado ainda. Gere o código e mande /start CÓDIGO para o bot.")
        try:
            return self.enviar_a_todos("✅ Teste do PDV: o Telegram está funcionando! Use os botões abaixo para acompanhar a casa.",
                                       TECLADO)
        except ErroTelegram as e:
            raise ErroNegocio(str(e)) from None

    def processar_fila(self) -> int:
        """Envia os avisos pendentes, na ordem. Levanta ErroTelegram (transitório) para a thread esperar e tentar de novo."""
        pendentes = self.banco.todos("SELECT * FROM telegram_fila WHERE status = 'pendente' ORDER BY id LIMIT 30")
        enviados = 0
        limite = (fmt.agora_dt() - timedelta(hours=FILA_VALIDADE_HORAS)).strftime("%Y-%m-%d %H:%M:%S")
        for item in pendentes:
            if item["criado_em"] < limite:
                self.banco.atualizar("telegram_fila", item["id"], {"status": "erro", "ultimo_erro": "vencido (sem conexão por muito tempo)"})
                continue
            chats = self.chats()
            if not chats:
                self.banco.atualizar("telegram_fila", item["id"], {"status": "erro", "ultimo_erro": "nenhum celular pareado"})
                continue
            entregues = {int(x) for x in item["entregue_a"].split(",") if x}
            try:
                for chat in chats:
                    if chat["chat_id"] in entregues:
                        continue
                    try:
                        self.cliente().enviar(chat["chat_id"], item["texto"])
                    except ErroTelegram as e:
                        if e.codigo == 403:                      # o dono bloqueou o bot: tira esse celular da lista
                            self.remover_chat(chat["chat_id"])
                            continue
                        raise
                    entregues.add(chat["chat_id"])
            except ErroTelegram as e:
                self.banco.atualizar("telegram_fila", item["id"], {
                    "tentativas": item["tentativas"] + 1, "entregue_a": ",".join(map(str, sorted(entregues))),
                    "ultimo_erro": str(e)[:200]})
                self._erro(str(e))
                if e.definitivo:                                 # token errado: não adianta insistir neste aviso
                    self.banco.atualizar("telegram_fila", item["id"], {"status": "erro"})
                raise
            self.banco.atualizar("telegram_fila", item["id"], {
                "status": "enviado", "enviado_em": fmt.agora(), "entregue_a": ",".join(map(str, sorted(entregues)))})
            enviados += 1
        if enviados:
            self._erro("")
        return enviados

    def limpar_antigos(self) -> None:
        corte = (fmt.agora_dt() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        self.banco.executar("DELETE FROM telegram_fila WHERE status <> 'pendente' AND criado_em < ?", (corte,))

    def resumo_agendado(self) -> bool:
        """Enfileira o resumo da noite que acabou, uma vez por dia, no horário configurado (nunca antes da virada do dia)."""
        hora = self.banco.cfg("telegram_resumo_hora").strip()
        if not hora or not notificacoes.ligado(self.banco, "resumo"):
            return False
        try:
            h, m = (int(x) for x in (fmt.para_hora(hora) or "").split(":"))
        except ValueError:
            return False
        agora = fmt.agora_dt()
        if (agora.hour, agora.minute) < max((h, m), (virada_dia(self.banco), 0)):
            return False
        dia = textos.dia_anterior(self.banco)
        if self.banco.cfg("telegram_ultimo_resumo") == dia:
            return False
        self.banco.cfg_set("telegram_ultimo_resumo", dia)
        notificacoes.enfileirar(self.banco, "resumo", textos.resumo(self.banco, dia, fechado=True))
        return True

    # ----------------------------------------------------- receber e responder
    def responder_comando(self, comando: str, argumento: str = "") -> str:
        b = self.banco
        if comando == "resumo":
            return textos.resumo(b)
        if comando == "ontem":
            return textos.resumo(b, textos.dia_anterior(b), fechado=True)
        if comando == "caixa":
            return textos.caixa(b)
        if comando == "top":
            return textos.mais_vendidos(b)
        if comando == "estoque":
            return textos.estoque(b)
        if comando == "abertas":
            return textos.abertas(b)
        if comando == "cancelamentos":
            return textos.cancelamentos(b)
        if comando == "semana":
            return textos.semana(b)
        if comando == "mes":
            return textos.mes(b)
        if comando == "horas":
            return textos.por_hora(b)
        if comando == "equipe":
            return textos.equipe(b)
        if comando == "contas":
            return textos.contas(b)
        if comando == "caderneta":
            return textos.caderneta(b)
        if comando == "comprar":
            return textos.comprar(b)
        if comando == "produto":
            return textos.produto(b, argumento)
        if comando == "mesa":
            return textos.mesa(b, argumento)
        return textos.ajuda()

    def tratar_mensagem(self, msg: dict) -> None:
        """Uma mensagem recebida pelo bot: pareamento, comando de quem é autorizado, ou recusa educada para estranhos."""
        chat = msg.get("chat") or {}
        chat_id, texto = chat.get("id"), (msg.get("text") or "").strip()
        if chat_id is None or chat.get("type") != "private" or not texto:
            return                                               # grupos, fotos, etc.: ignora
        cliente = self.cliente()
        nome = " ".join(x for x in ((msg.get("from") or {}).get("first_name"), (msg.get("from") or {}).get("last_name")) if x)
        autorizado = bool(self.banco.valor("SELECT 1 FROM telegram_chats WHERE chat_id = ?", (chat_id,)))

        partes = texto.split()
        if partes[0].lower().split("@")[0] == "/start":
            tentado = partes[1] if len(partes) > 1 else ""
            if tentado and self._conferir_codigo(tentado):
                self._parear(chat_id, nome)
                cliente.enviar(chat_id, "✅ Conectado! A partir de agora você recebe os avisos da casa aqui e pode tocar nos "
                                        "botões para ver o que está acontecendo.\n\n" + textos.ajuda(), TECLADO)
                return
            if autorizado:
                cliente.enviar(chat_id, textos.ajuda(), TECLADO)
                return
            cliente.enviar(chat_id, "🔒 Este bot é privado. Para conectar, abra o PDV em Configurações > Telegram, toque em "
                                    "Gerar código e envie aqui: /start CÓDIGO" if not tentado else
                                    "🔒 Código inválido ou vencido. Gere outro no PDV (Configurações > Telegram).")
            return
        if not autorizado:
            cliente.enviar(chat_id, "🔒 Este bot é privado.")
            return
        if not self.banco.cfg_bool("telegram_ativo", False):
            cliente.enviar(chat_id, "O Telegram está desligado no PDV (Configurações > Telegram).")
            return
        entendido = interpretar(texto)
        if entendido is None:
            achado = self._produto_digitado(texto)         # "skol" sozinho: o dono quer ver o produto
            if achado:
                cliente.enviar(chat_id, achado, TECLADO)
            else:
                cliente.enviar(chat_id, "Não entendi. Toque em um dos botões:", TECLADO)
            return
        comando, argumento = entendido
        try:
            resposta = self.responder_comando(comando, argumento)
        except Exception:  # noqa: BLE001 - uma consulta com problema não derruba o bot
            log.exception("Falha ao montar a resposta '%s' do Telegram.", comando)
            resposta = "Não consegui montar essa informação agora. Tente de novo em instantes."
        cliente.enviar(chat_id, resposta, TECLADO)

    def _produto_digitado(self, texto: str) -> str | None:
        """Texto que não é comando: se bater com produto(s) cadastrado(s), devolve o resultado da busca; senão None."""
        t = texto.strip()
        if len(t) < 2 or len(t) > 40 or t.startswith("/"):
            return None
        try:
            resposta = textos.produto(self.banco, t)
        except Exception:  # noqa: BLE001
            return None
        return None if resposta.startswith("🔎 Não achei") else resposta

    def processar_atualizacoes(self, espera: int = 25) -> int:
        """Pergunta ao Telegram se há mensagens novas e trata cada uma. Devolve quantas chegaram."""
        offset = self.banco.cfg_int("telegram_offset", 0)
        novas = self.cliente().atualizacoes(offset, espera)
        for u in novas:
            offset = max(offset, u["update_id"] + 1)
            try:
                self.banco.cfg_set("telegram_offset", offset)    # grava antes de tratar: não repete se algo travar
                if u.get("message"):
                    self.tratar_mensagem(u["message"])
            except ErroTelegram as e:
                log.warning("Telegram: não consegui responder (%s).", e)
            except Exception:  # noqa: BLE001
                log.exception("Telegram: erro ao tratar uma mensagem.")
        return len(novas)


class ServicoTelegram:
    """Duas threads de segundo plano (cada uma com a sua conexão ao banco, que precisa ser arquivo):
    uma envia a fila de avisos e o resumo diário; a outra escuta o bot (long polling)."""

    def __init__(self, caminho_banco: str, http=None):
        if caminho_banco == ":memory:":
            raise ErroNegocio("O Telegram em segundo plano precisa de banco em arquivo.")
        self.caminho, self.http = caminho_banco, http
        self._parar = threading.Event()
        self._threads: list[threading.Thread] = []
        self.ultimo_erro: str | None = None

    @property
    def ativo(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._threads = [threading.Thread(target=self._laco_envio, name="telegram-envio", daemon=True),
                         threading.Thread(target=self._laco_escuta, name="telegram-escuta", daemon=True)]
        for t in self._threads:
            t.start()

    def parar(self, timeout: float = 3.0) -> None:
        self._parar.set()
        notificacoes.ACORDAR.set()
        for t in self._threads:
            t.join(timeout)        # a escuta pode estar esperando o Telegram (até 25 s): é thread 'daemon', morre com o programa

    def _abrir(self):
        from src.database.conexao import BancoDados     # import tardio: evita ciclo na carga dos módulos
        return TelegramController(BancoDados(self.caminho, semear=False), self.http)

    def _laco_envio(self) -> None:
        try:
            ctl = self._abrir()
        except Exception as e:  # noqa: BLE001
            self.ultimo_erro = f"Telegram não abriu o banco: {e}"
            return
        falhas, ultima_limpeza = 0, 0.0
        try:
            while not self._parar.is_set():
                espera = 30.0
                try:
                    if ctl.token:
                        ctl.resumo_agendado()
                        ctl.processar_fila()
                        falhas = 0
                        ultima_limpeza += espera
                        if ultima_limpeza > 3600:
                            ctl.limpar_antigos()
                            ultima_limpeza = 0.0
                except ErroTelegram as e:
                    self.ultimo_erro = str(e)
                    falhas += 1
                    espera = ESPERAS[min(falhas - 1, len(ESPERAS) - 1)]
                except Exception as e:  # noqa: BLE001 - a thread não pode morrer
                    self.ultimo_erro = str(e)
                    log.exception("Telegram: erro no envio.")
                notificacoes.ACORDAR.wait(espera)
                notificacoes.ACORDAR.clear()
        finally:
            ctl.banco.fechar()

    def _laco_escuta(self) -> None:
        try:
            ctl = self._abrir()
        except Exception as e:  # noqa: BLE001
            self.ultimo_erro = f"Telegram não abriu o banco: {e}"
            return
        falhas = 0
        try:
            while not self._parar.is_set():
                if not ctl.token:
                    self._parar.wait(5)
                    continue
                try:
                    ctl.processar_atualizacoes(25)
                    falhas = 0
                    ctl._erro("")
                except ErroTelegram as e:
                    self.ultimo_erro = str(e)
                    ctl._erro("Outro programa está usando este bot (feche-o ou crie outro bot)." if e.codigo == 409 else str(e))
                    falhas += 1
                    self._parar.wait(60 if e.definitivo or e.codigo == 409 else ESPERAS[min(falhas - 1, len(ESPERAS) - 1)])
                except Exception as e:  # noqa: BLE001
                    self.ultimo_erro = str(e)
                    log.exception("Telegram: erro ao escutar o bot.")
                    self._parar.wait(10)
        finally:
            ctl.banco.fechar()
