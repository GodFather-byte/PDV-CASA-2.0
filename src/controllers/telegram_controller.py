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

import importlib
import json
import logging
import re
import secrets
import threading
from datetime import timedelta

from src.controllers import notificacoes, telegram_textos as textos
from src.core import formatacao as fmt
from src.core import licenca
from src.core.erros import ErroNegocio
from src.database.sementes import aplicar_padrao_telegram_23h
from src.sync.telegram_api import ClienteTelegram, ErroTelegram

log = logging.getLogger("pdv.telegram")

CODIGO_VALIDADE_MIN = 10
CODIGO_MAX_ERROS = 5
FILA_VALIDADE_HORAS = 48          # aviso mais velho que isto não é mais notícia: vira 'erro' em vez de chegar atrasado
ESPERAS = (5, 10, 20, 40, 60)     # segundos entre tentativas quando o Telegram não responde; a última se repete
TIPO_RESUMO = "resumo_agendado"
CHAVE_AGENDAMENTO = "telegram_resumo_agendamento"

# Os botões do teclado do bot: (texto do botão, comando interno). Quem digitar "/resumo" ou "resumo" também funciona.
BOTOES = [("📊 Resumo", "resumo"), ("📅 Ontem", "ontem"), ("💵 Caixa", "caixa"), ("🍺 Mais vendidos", "top"),
          ("📦 Estoque", "estoque"), ("🛒 Comprar", "comprar"), ("🪑 Abertas", "abertas"), ("❌ Cancelamentos", "cancelamentos"),
          ("🧭 Gerencial", "gerencial"), ("🚨 Alertas", "alertas"),
          ("📈 Semana", "semana"), ("🗓️ Mês", "mes"), ("🕐 Por hora", "horas"), ("👥 Equipe", "equipe"),
          ("💳 Contas", "contas"), ("📒 Caderneta", "caderneta"), ("🔎 Produto", "produto"),
          ("🔐 Licença", "licenca"), ("🛟 Suporte", "suporte"), ("🔄 Renovar", "renovar"), ("❓ Ajuda", "ajuda")]
# Duas colunas; se a quantidade for ímpar, o último botão fica sozinho na linha.
TECLADO = [[texto for texto, _ in BOTOES[i:i + 2]] for i in range(0, len(BOTOES), 2)]
_COMANDOS = {texto: cmd for texto, cmd in BOTOES}
_COMANDOS.update({cmd: cmd for _, cmd in BOTOES})
_COMANDOS.update({"mais vendidos": "top", "cancelamentos": "cancelamentos", "ajuda": "ajuda", "help": "ajuda", "menu": "ajuda",
                  "mês": "mes", "por hora": "horas", "hora": "horas", "compras": "comprar", "lista de compras": "comprar",
                  "vendas da semana": "semana", "semanal": "semana", "mensal": "mes", "garçons": "equipe", "garcons": "equipe",
                  "devedores": "caderneta", "mesas": "abertas", "produtos": "produto", "mesa": "mesa", "comanda": "mesa",
                  "licença": "licenca", "saude": "suporte", "saúde": "suporte", "central": "suporte",
                  "status": "suporte", "renovação": "renovar", "renovacao": "renovar",
                  "alerta": "alertas", "avisos": "alertas", "pendências": "alertas", "pendencias": "alertas",
                  "painel": "gerencial", "gestão": "gerencial", "gestao": "gerencial"})
CHAVE_AVISO_LICENCA = "telegram_licenca_aviso"   # 'dia|validade|situação' do último aviso de licença (não repetir)
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
        aplicar_padrao_telegram_23h(banco)
        self._http = http          # nos testes, um falso: http(url, dados, timeout) -> dict
        self.chave_publica = None  # nos testes, a chave pública de teste; None = a chave real embutida no PDV
        self.http_ponte = None     # repassado à ponte com o fornecedor (None = HTTP real dela)

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
            self.banco.executar("DELETE FROM telegram_fila WHERE tipo = ?", (TIPO_RESUMO,))
            if self.banco.cfg(CHAVE_AGENDAMENTO):
                self.banco.cfg_set(CHAVE_AGENDAMENTO, "")
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
        estado = self._agendamento()
        if estado.get("fila_id"):
            item = self.banco.um("SELECT entregue_a FROM telegram_fila WHERE id = ?", (estado["fila_id"],))
            anteriores = set(estado["chats"]) & {c["chat_id"] for c in self.chats()}
            if item and not item["entregue_a"] and not anteriores:
                with self.banco.transacao():
                    self.banco.atualizar("telegram_fila", estado["fila_id"], {
                        "status": "erro", "ultimo_erro": "substituído após novo pareamento autorizado"})
                    self._salvar_agendamento({"inicio": estado["inicio"],
                                              "ultimo_envio": estado.get("ultimo_envio", "")})
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
        if not self.ligado():
            return 0
        if self.banco.cfg(CHAVE_AGENDAMENTO) and self._agendamento().get("fila_id"):
            self.resumo_agendado()
        pendentes = self.banco.todos("SELECT * FROM telegram_fila WHERE status = 'pendente' ORDER BY id LIMIT 30")
        enviados = 0
        limite = (fmt.agora_dt() - timedelta(hours=FILA_VALIDADE_HORAS)).strftime("%Y-%m-%d %H:%M:%S")
        for item in pendentes:
            agendado = item["tipo"] == TIPO_RESUMO
            estado = self._agendamento() if agendado else {}
            if agendado and (not self._resumo_ativo() or estado.get("fila_id") != item["id"]):
                continue
            if not agendado and item["criado_em"] < limite:
                self.banco.atualizar("telegram_fila", item["id"], {"status": "erro", "ultimo_erro": "vencido (sem conexão por muito tempo)"})
                continue
            chats = self.chats()
            if agendado:
                chats = [c for c in chats if c["chat_id"] in estado["chats"]]
            if not chats:
                if agendado:
                    continue
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
                    # Persistir cada sucesso reduz repetição se o processo cair entre dois celulares.
                    self.banco.atualizar("telegram_fila", item["id"], {
                        "entregue_a": ",".join(map(str, sorted(entregues)))})
            except ErroTelegram as e:
                self.banco.atualizar("telegram_fila", item["id"], {
                    "tentativas": item["tentativas"] + 1, "entregue_a": ",".join(map(str, sorted(entregues))),
                    "ultimo_erro": str(e)[:200]})
                self._erro(str(e))
                if e.definitivo and not agendado:
                    self.banco.atualizar("telegram_fila", item["id"], {"status": "erro"})
                raise
            if agendado and not entregues:
                continue
            with self.banco.transacao():
                self.banco.atualizar("telegram_fila", item["id"], {
                    "status": "enviado", "enviado_em": fmt.agora(), "entregue_a": ",".join(map(str, sorted(entregues)))})
                if agendado:
                    self._salvar_agendamento({"inicio": estado["fim"], "ultimo_envio": fmt.agora()})
                    self.banco.cfg_set("telegram_ultimo_resumo", estado["fim"])
            enviados += 1
        if enviados:
            self._erro("")
        return enviados

    def limpar_antigos(self) -> None:
        corte = (fmt.agora_dt() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        self.banco.executar("DELETE FROM telegram_fila WHERE status <> 'pendente' AND criado_em < ?", (corte,))

    def _salvar_agendamento(self, estado: dict) -> None:
        self.banco.cfg_set(CHAVE_AGENDAMENTO, json.dumps(estado, ensure_ascii=False))

    def _agendamento(self) -> dict:
        gravado = self.banco.cfg(CHAVE_AGENDAMENTO)
        if gravado:
            return json.loads(gravado)
        # A marca antiga era gravada ANTES do envio: não é prova de entrega.
        # Começar no dia do pareamento mais antigo recupera o que não foi confirmado.
        desde = self.banco.valor("SELECT MIN(criado_em) FROM telegram_chats")
        estado = {"inicio": (desde or fmt.agora())[:10] + " 00:00:00", "ultimo_envio": ""}
        if desde:
            with self.banco.transacao():
                self.banco.executar(
                    "UPDATE telegram_fila SET status = 'erro', ultimo_erro = ? "
                    "WHERE tipo = 'resumo' AND status = 'pendente'",
                    ("substituído pelo resumo consolidado; período preservado no agendamento",))
                self._salvar_agendamento(estado)
        return estado

    def _resumo_ativo(self) -> bool:
        return (self.banco.cfg_bool("telegram_resumo_ativo", True)
                and bool(self.banco.cfg("telegram_resumo_hora", "23:00").strip()))

    def salvar_agendamento(self, ativo: bool, hora: str) -> None:
        try:
            h, m = (int(x) for x in (fmt.para_hora(hora) or "").split(":"))
        except (ValueError, TypeError):
            raise ErroNegocio("Horário do resumo inválido. Use hh:mm, por exemplo 23:00.") from None
        with self.banco.transacao():
            self.banco.cfg_set("telegram_resumo_ativo", "S" if ativo else "N")
            self.banco.cfg_set("telegram_resumo_hora", f"{h:02d}:{m:02d}")
        notificacoes.ACORDAR.set()

    def estado_agendamento(self) -> dict:
        """Estado público local, sem rede nem credenciais; pendência sobrevive a falhas/reinício."""
        estado = self._agendamento()
        item = (self.banco.um("SELECT status, ultimo_erro, entregue_a FROM telegram_fila WHERE id = ?",
                             (estado["fila_id"],)) if estado.get("fila_id") else None)
        return {**estado, "ativo": self._resumo_ativo(),
                "hora": self.banco.cfg("telegram_resumo_hora", "23:00"),
                "pendente": bool(estado.get("fila_id")), "telegram_ligado": self.ligado(),
                "erro_pendente": item["ultimo_erro"] if item else ""}

    def texto_agendamento(self) -> str:
        estado = self.estado_agendamento()
        situacao = "ativo" if estado["ativo"] else "pausado"
        mensagem = f"Resumo {situacao}, diariamente às {estado['hora'] or '—'} (horário local)."
        if estado["pendente"]:
            mensagem += f" Pendente: {estado['inicio']} até {estado['fim']}; nova tentativa automática quando ligado."
        elif estado.get("ultimo_envio"):
            mensagem += f" Último envio confirmado: {estado['ultimo_envio']}."
        else:
            mensagem += f" Período acompanhado desde {estado['inicio']}."
        return mensagem

    def resumo_agendado(self) -> bool:
        """Um intervalo pendente, consolidado até o último horário local vencido."""
        if not self._resumo_ativo() or not notificacoes.ligado(self.banco, "resumo"):
            return False
        try:
            h, m = (int(x) for x in (fmt.para_hora(self.banco.cfg("telegram_resumo_hora", "23:00")) or "").split(":"))
        except ValueError:
            return False
        agora = fmt.agora_dt()
        vencido = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        if agora < vencido:
            vencido -= timedelta(days=1)
        fim = vencido.strftime("%Y-%m-%d %H:%M:%S")
        with self.banco.transacao():
            estado = self._agendamento()
            if fim <= estado["inicio"]:
                return False
            if estado.get("fila_id"):
                item = self.banco.um("SELECT * FROM telegram_fila WHERE id = ?", (estado["fila_id"],))
                if not item:
                    # Remoção manual da fila não deve apagar o intervalo recuperável.
                    estado["fila_id"] = notificacoes.enfileirar(
                        self.banco, TIPO_RESUMO,
                        textos.resumo_agendado(self.banco, estado["inicio"], estado["fim"]))
                    self._salvar_agendamento(estado)
                    return True
                if item and not item["entregue_a"] and fim > estado["fim"]:
                    estado["fim"] = fim
                    self.banco.atualizar("telegram_fila", item["id"], {
                        "texto": textos.resumo_agendado(self.banco, estado["inicio"], fim)})
                    self._salvar_agendamento(estado)
                return False
            estado.update(fim=fim, chats=[c["chat_id"] for c in self.chats()])
            estado["fila_id"] = notificacoes.enfileirar(
                self.banco, TIPO_RESUMO, textos.resumo_agendado(self.banco, estado["inicio"], fim))
            self._salvar_agendamento(estado)
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
        if comando == "alertas":
            return textos.alertas(b)
        if comando == "gerencial":
            return textos.gerencial(b)
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
        if comando == "licenca":
            return textos.licenca(self._estado_licenca(), self._pedido_pendente())
        if comando == "suporte":
            from src.versao import VERSAO
            fila = b.valor("SELECT COUNT(*) FROM telegram_fila WHERE status = 'pendente'", padrao=0)
            return textos.suporte(VERSAO, self._estado_licenca(), self._situacao_ponte(), fila, bool(self.ultimo_erro()))
        if comando == "renovar":
            return self.pedir_renovacao()
        return textos.ajuda()

    # ---------------------------------------------------- licença e fornecedor
    def _estado_licenca(self):
        return licenca.estado(self.banco, chave_publica=self.chave_publica)

    @staticmethod
    def _ponte():
        """O módulo da ponte com o fornecedor, ou None enquanto ele não existir nesta instalação."""
        try:
            return importlib.import_module("src.sync.ponte")
        except ModuleNotFoundError as e:
            if e.name in ("src.sync.ponte", "src.sync"):
                return None
            raise

    def _situacao_ponte(self) -> dict | None:
        """Retrato LOCAL do contato com o fornecedor, lido de `ponte.estado(banco)` (sem rede), reduzido ao que o dono
        pode ver: ligada, último contato, se houve erro (sem o texto) e o andamento do pedido. None = ponte ausente."""
        ponte = self._ponte()
        leitor = getattr(ponte, "estado", None) if ponte else None
        if leitor is None:
            return None
        try:
            dados = leitor(self.banco)
        except Exception as e:  # noqa: BLE001 - consulta de suporte não pode derrubar o bot
            log.warning("Telegram: falha ao ler a situação da ponte (%s).", type(e).__name__)   # o texto pode ter credencial
            return {"ativa": True, "com_erro": True}
        if not isinstance(dados, dict):
            return None
        if not dados.get("ativa"):
            return {"ativa": False}
        pedido = None
        if str(dados.get("solicitacao_id") or "").strip() and str(dados.get("solicitacao_estado") or "").strip():
            pedido = {"status": str(dados["solicitacao_estado"]).strip()}
        return {"ativa": True, "ultimo_contato": dados.get("ultimo_sucesso") or "", "com_erro": bool(dados.get("erro")),
                "pedido": pedido}

    def _pedido_pendente(self):
        situacao = self._situacao_ponte()
        return situacao.get("pedido") if situacao else None

    def pedir_renovacao(self) -> str:
        """Só PEDE a renovação ao fornecedor, pela ponte: não emite licença nem cobra. Faz rede, então roda na thread do
        bot, nunca na tela. Só diz 'entregue' quando a ponte registra o pedido como enviado à central."""
        if self._estado_licenca().situacao == "desativada":
            return "ℹ️ A licença não é exigida neste caixa: não há o que renovar."
        ponte = self._ponte()
        solicitar = getattr(ponte, "solicitar_renovacao", None) if ponte else None
        if solicitar is None:
            return ("❌ O pedido de renovação pelo Telegram ainda não está disponível neste caixa. "
                    "Fale com o fornecedor pelo canal de sempre.")
        antes = self._pedido_pendente()
        try:
            resultado = solicitar(self.banco, http=self.http_ponte)
        except ErroNegocio as e:
            return f"❌ Não foi possível pedir a renovação: {str(e)[:300]}\nNada foi alterado na licença."
        except Exception as e:  # noqa: BLE001 - rede, servidor fora do ar etc.: sem detalhe técnico no chat nem no log
            log.warning("Telegram: falha ao pedir a renovação (%s).", type(e).__name__)
            return "❌ Não consegui enviar o pedido de renovação agora. Nada foi alterado; tente de novo mais tarde."
        pedido_id = resultado.get("id") if isinstance(resultado, dict) else resultado
        if not isinstance(pedido_id, str) or not pedido_id.strip():
            log.warning("Telegram: a ponte não confirmou o pedido de renovação (%s).", type(resultado).__name__)
            return "❌ O pedido de renovação não foi registrado. Nada foi alterado; tente de novo mais tarde."
        depois = self._pedido_pendente() or {}
        status = depois.get("status") or (resultado.get("status") if isinstance(resultado, dict) else "") or ""
        repetido = bool(antes and antes.get("status") == "enviada" and status == "enviada")
        self.banco.log("telegram_renovacao_pedida", f"pedido {pedido_id.strip()[:60]} ({status or '?'})")
        return textos.renovacao_pedida(entregue=status == "enviada", repetido=repetido, atendida=status == "atendida")

    def aviso_licenca(self) -> bool:
        """Enfileira o aviso de licença (vencendo, em carência, bloqueada, sem licença válida ou renovada e já aplicada)
        no máximo uma vez por dia/validade/situação. A marca é gravada na mesma transação do aviso: reiniciar não repete.
        Só roda com o Telegram ligado e celular pareado; licença não exigida não avisa. Nunca levanta erro."""
        b = self.banco
        texto = ""
        try:
            if not notificacoes.ligado(b, "licenca"):
                return False
            est = self._estado_licenca()
            if est.situacao == "desativada":
                return False
            validade = est.expira_em.isoformat() if est.expira_em else ""
            marca = f"{fmt.hoje()}|{validade}|{est.situacao}"
            anterior = b.cfg(CHAVE_AVISO_LICENCA)
            if marca == anterior:
                return False
            validade_anterior = (anterior.split("|") + ["", ""])[1]
            renovada = bool(validade and validade_anterior and validade > validade_anterior)
            texto = textos.licenca_alerta(est, renovada)
            with b.transacao():
                if texto:
                    b.inserir("telegram_fila", {"criado_em": fmt.agora(), "tipo": "licenca", "texto": texto})
                b.cfg_set(CHAVE_AVISO_LICENCA, marca)
        except Exception:  # noqa: BLE001 - aviso é acessório
            log.exception("Telegram: falha ao verificar a licença para avisar.")
            return False
        if texto:
            notificacoes.ACORDAR.set()
        return bool(texto)

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
                        ctl.aviso_licenca()
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
