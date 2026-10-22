"""Central exclusiva do fornecedor: cadastro, emissão local e ponte HTTPS."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from licenciador import nucleo
from src.core import formatacao as fmt, licenca
from src.core.erros import ErroNegocio


class ErroCentral(ErroNegocio):
    """Falha exibível sem credenciais ou dados privados."""


def caminho_padrao() -> Path:
    base = Path(os.environ.get("WILLCENTRAL_DADOS") or
                Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WillPDV-Central")
    return base / "central.db"


def chave_loja(valor: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", valor):
        raise ErroCentral("Use uma chave de loja com até 64 letras, números, ponto, hífen ou sublinhado.")
    return valor


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ClientePonte:
    def __init__(self, url: str, token: str, transporte=None):
        base = url.strip().rstrip("/")
        if base.endswith("/v1/sincronizar"):
            base = base[:-len("/v1/sincronizar")]
        partes = urllib.parse.urlsplit(base)
        if (partes.scheme != "https" and not
                (partes.scheme == "http" and partes.hostname in ("localhost", "127.0.0.1", "::1"))):
            raise ErroCentral("A ponte exige HTTPS (HTTP somente em localhost).")
        if not partes.hostname or partes.username or partes.password or partes.query or partes.fragment:
            raise ErroCentral("Endereço da ponte inválido.")
        if not token.strip():
            raise ErroCentral("Configure o token exclusivo da central.")
        self.url, self.token, self.transporte = base, token.strip(), transporte

    def chamar(self, metodo: str, rota: str, dados: dict | None = None) -> dict:
        if self.transporte is not None:
            resultado = self.transporte(metodo, rota, dados)
        else:
            req = urllib.request.Request(
                self.url + rota, method=metodo,
                data=None if dados is None else json.dumps(dados).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            try:
                with urllib.request.build_opener(_SemRedirecionar()).open(req, timeout=15) as resposta:
                    resultado = json.loads(resposta.read(2_000_001).decode("utf-8"))
            except urllib.error.HTTPError as erro:
                raise ErroCentral(f"A ponte recusou a operação (HTTP {erro.code}).") from None
            except (OSError, ValueError, urllib.error.URLError):
                raise ErroCentral("Não foi possível comunicar com a ponte. Confira conexão e configuração.") from None
        if not isinstance(resultado, dict):
            raise ErroCentral("Resposta inválida da ponte.")
        return resultado


class Central:
    def __init__(self, arquivo: Path | None = None, ponte: ClientePonte | None = None,
                 arquivo_chave: Path | None = None):
        self.arquivo = Path(arquivo) if arquivo is not None else caminho_padrao()
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.arquivo, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.ponte, self.arquivo_chave = ponte, arquivo_chave
        try:
            self._migrar()
        except (sqlite3.Error, ErroCentral):
            self.db.close()
            raise

    def _migrar(self) -> None:
        versao = self.db.execute("PRAGMA user_version").fetchone()[0]
        if versao > 1:
            raise ErroCentral("Banco da central mais novo que este programa.")
        if versao == 0:
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                raise ErroCentral("O arquivo contém outro banco. Escolha um arquivo novo exclusivo da central.")
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE lojas (
                    chave TEXT PRIMARY KEY COLLATE NOCASE, nome TEXT NOT NULL, ativa INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE licencas (
                    id TEXT PRIMARY KEY, loja TEXT NOT NULL REFERENCES lojas(chave),
                    codigo TEXT NOT NULL UNIQUE, emitida_em TEXT NOT NULL, expira_em TEXT NOT NULL,
                    publicada INTEGER NOT NULL DEFAULT 0, origem TEXT NOT NULL);
                CREATE TABLE administradores (chat_id INTEGER PRIMARY KEY);
                CREATE TABLE confirmacoes (
                    hash TEXT PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES administradores(chat_id),
                    loja TEXT NOT NULL REFERENCES lojas(chave), meses INTEGER NOT NULL,
                    ate TEXT NOT NULL, usada INTEGER NOT NULL DEFAULT 0, licenca_id TEXT);
                CREATE TABLE retratos (tipo TEXT PRIMARY KEY, dados TEXT NOT NULL, recebido_em TEXT NOT NULL);
                CREATE TABLE config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
                CREATE TABLE eventos (
                    id INTEGER PRIMARY KEY, quando TEXT NOT NULL, chat_id INTEGER,
                    evento TEXT NOT NULL, detalhe TEXT NOT NULL);
                PRAGMA user_version=1;
                COMMIT;
            """)
        tabelas = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"lojas", "licencas", "administradores", "confirmacoes", "retratos", "config", "eventos"} <= tabelas:
            raise ErroCentral("Este arquivo não é um banco completo da central.")

    def fechar(self) -> None:
        self.db.close()

    def _evento(self, evento: str, detalhe: str, chat_id: int | None = None) -> None:
        self.db.execute("INSERT INTO eventos(quando,chat_id,evento,detalhe) VALUES(?,?,?,?)",
                        (fmt.agora(), chat_id, evento, detalhe))

    def config(self, chave: str, padrao: str = "") -> str:
        r = self.db.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
        return r[0] if r else padrao

    def configurar(self, chave: str, valor: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO config VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                            (chave, valor))

    def cadastrar(self, chave: str, nome: str, ativa: bool = True) -> str:
        chave = chave_loja(chave)
        if not isinstance(nome, str) or not 1 <= len(nome.strip()) <= 160 or type(ativa) is not bool:
            raise ErroCentral("Informe nome de até 160 caracteres e situação válida.")
        with self.db:
            self.db.execute("INSERT INTO lojas VALUES(?,?,?) ON CONFLICT(chave) DO UPDATE "
                            "SET nome=excluded.nome, ativa=excluded.ativa", (chave, nome.strip(), int(ativa)))
            self._evento("loja_cadastrada", chave)
        return chave

    def administrador(self, chat_id: int, remover: bool = False) -> None:
        if type(chat_id) is not int or chat_id <= 0:
            raise ErroCentral("Informe o ID numérico de um usuário privado do Telegram.")
        with self.db:
            if remover:
                self.db.execute("DELETE FROM confirmacoes WHERE chat_id=?", (chat_id,))
                self.db.execute("DELETE FROM administradores WHERE chat_id=?", (chat_id,))
            else:
                self.db.execute("INSERT OR IGNORE INTO administradores VALUES(?)", (chat_id,))
            self._evento("administrador_removido" if remover else "administrador_adicionado", str(chat_id))

    def autorizado(self, chat_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM administradores WHERE chat_id=?", (chat_id,)).fetchone() is not None

    def lojas(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT l.*, (SELECT MAX(expira_em) FROM licencas WHERE loja=l.chave) AS validade "
            "FROM lojas l ORDER BY l.chave")]

    def importar_historico(self, origem: Path) -> int:
        try:
            dados = json.loads(Path(origem).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ErroCentral("Não foi possível ler o histórico. O original não foi alterado.") from None
        if not isinstance(dados, list):
            raise ErroCentral("O histórico precisa ser uma lista de licenças.")
        validadas = []
        for item in dados:
            if not isinstance(item, dict) or not isinstance(item.get("codigo"), str):
                raise ErroCentral("Histórico contém registro sem código de licença.")
            validada = licenca.ler_licenca(item["codigo"])
            chave = chave_loja(validada["loja"])
            validadas.append((item["codigo"], validada, chave))
        quantidade = 0
        with self.db:
            for codigo, validada, chave in validadas:
                self.db.execute("INSERT OR IGNORE INTO lojas VALUES(?,?,1)", (chave, validada["loja"]))
                chave = self.db.execute("SELECT chave FROM lojas WHERE chave=?", (chave,)).fetchone()[0]
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO licencas VALUES(?,?,?,?,?,0,'historico')",
                    (str(uuid4()), chave, codigo, validada["emitida_em"].isoformat(),
                     validada["expira_em"].isoformat()))
                quantidade += cursor.rowcount
            self._evento("historico_importado", str(quantidade))
        return quantidade

    def preparar_emissao(self, chat_id: int, loja: str, meses: int) -> str:
        if not self.autorizado(chat_id):
            raise ErroCentral("Administrador não autorizado.")
        if self.config("recuperacao_pendente") == "S":
            raise ErroCentral("Sincronize a central restaurada com a ponte antes de emitir.")
        loja = chave_loja(loja)
        if type(meses) is not int or not 1 <= meses <= 60:
            raise ErroCentral("Informe de 1 a 60 meses.")
        r = self.db.execute("SELECT chave,ativa FROM lojas WHERE chave=?", (loja,)).fetchone()
        if r is None or not r["ativa"]:
            raise ErroCentral("Loja inexistente ou desativada na central.")
        loja = r["chave"]
        token = secrets.token_urlsafe(12)
        ate = (fmt.agora_dt() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db:
            self.db.execute("INSERT INTO confirmacoes VALUES(?,?,?,?,?,0,NULL)",
                            (hashlib.sha256(token.encode()).hexdigest(), chat_id, loja, meses, ate))
            self._evento("emissao_solicitada", f"{loja}; meses={meses}", chat_id)
        return token

    def confirmar_emissao(self, chat_id: int, token: str) -> str:
        if not self.autorizado(chat_id):
            raise ErroCentral("Administrador não autorizado.")
        digest = hashlib.sha256(token.encode()).hexdigest()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            pedido = self.db.execute("SELECT * FROM confirmacoes WHERE hash=? AND chat_id=?",
                                     (digest, chat_id)).fetchone()
            if pedido is None:
                raise ErroCentral("Confirmação inválida para este administrador.")
            if pedido["usada"]:
                self.db.commit()
                return pedido["licenca_id"]
            if self.config("recuperacao_pendente") == "S":
                raise ErroCentral("Sincronize a central restaurada com a ponte antes de emitir.")
            identificador = str(uuid5(NAMESPACE_URL, f"willpdv-central:{chat_id}:{digest}"))
            existente = self.db.execute("SELECT id FROM licencas WHERE id=?", (identificador,)).fetchone()
            if existente:
                self.db.execute("UPDATE confirmacoes SET usada=1,licenca_id=? WHERE hash=?",
                                (identificador, digest))
                self.db.commit()
                return identificador
            if pedido["ate"] <= fmt.agora():
                raise ErroCentral("Confirmação vencida. Solicite outra emissão.")
            loja = self.db.execute("SELECT ativa FROM lojas WHERE chave=?", (pedido["loja"],)).fetchone()
            if not loja or not loja["ativa"]:
                raise ErroCentral("Loja desativada.")
            ultima = self.db.execute("SELECT MAX(expira_em) FROM licencas WHERE loja=?",
                                     (pedido["loja"],)).fetchone()[0]
            hoje = date.fromisoformat(fmt.hoje())
            base = max(hoje, date.fromisoformat(ultima)) if ultima else hoje
            if ultima:
                anterior = self.db.execute(
                    "SELECT codigo FROM licencas WHERE loja=? ORDER BY expira_em DESC LIMIT 1",
                    (pedido["loja"],)).fetchone()
                lida = licenca.ler_licenca(anterior["codigo"])
                if (lida["expira_em"] - lida["emitida_em"]).days >= licenca.MAX_DIAS - 1:
                    raise ErroCentral("Licença permanente não pode ser renovada automaticamente.")
            expira = date.fromisoformat(fmt.somar_meses(base.isoformat(), pedido["meses"]))
            estado = nucleo.estado_chave(self.arquivo_chave)
            if not estado.pronta:
                raise ErroCentral(estado.mensagem)
            semente = nucleo._ler_semente(self.arquivo_chave or nucleo.arquivo_chave())
            codigo = licenca.gerar_licenca(semente, pedido["loja"], (expira - hoje).days, hoje)
            licenca.ler_licenca(codigo)
            self.db.execute("INSERT INTO licencas VALUES(?,?,?,?,?,0,'central')",
                            (identificador, pedido["loja"], codigo, hoje.isoformat(), expira.isoformat()))
            self.db.execute("UPDATE confirmacoes SET usada=1,licenca_id=? WHERE hash=?",
                            (identificador, digest))
            self._evento("licenca_emitida", f"{pedido['loja']}; id={identificador}", chat_id)
            self.db.commit()
            return identificador
        except (sqlite3.Error, ErroNegocio, OSError, ValueError):
            self.db.rollback()
            raise

    def _cliente(self) -> ClientePonte:
        if self.ponte is None:
            raise ErroCentral("Configure a conexão da central com a ponte.")
        return self.ponte

    def provisionar(self, loja: str, caixa_id: str) -> str:
        loja = chave_loja(loja)
        try:
            caixa_id = str(UUID(caixa_id))
        except (ValueError, TypeError, AttributeError):
            raise ErroCentral("Informe o UUID do caixa mostrado nas configurações do PDV.") from None
        r = self.db.execute("SELECT * FROM lojas WHERE chave=?", (loja,)).fetchone()
        if not r or not r["ativa"]:
            raise ErroCentral("Cadastre e ative a loja antes de aprovar o caixa.")
        loja = r["chave"]
        cliente = self._cliente()
        cliente.chamar("PUT", "/v1/central/lojas/" + urllib.parse.quote(loja, safe=""),
                       {"nome": r["nome"], "ativa": True})
        resposta = cliente.chamar("POST", "/v1/central/caixas", {"chave_loja": loja, "caixa_id": caixa_id})
        token = resposta.get("token")
        if not isinstance(token, str) or not token:
            raise ErroCentral("A ponte não devolveu a credencial do caixa.")
        with self.db:
            self._evento("caixa_aprovado", f"{loja}; {caixa_id}")
        return token

    def revogar_caixa(self, caixa_id: str) -> None:
        try:
            caixa_id = str(UUID(caixa_id))
        except (ValueError, TypeError, AttributeError):
            raise ErroCentral("UUID do caixa inválido.") from None
        self._cliente().chamar("POST", f"/v1/central/caixas/{caixa_id}/revogar", {})
        with self.db:
            self._evento("caixa_revogado", caixa_id)

    def autorizar_publicacao(self, loja: str) -> str:
        loja = chave_loja(loja)
        cadastrada = self.db.execute("SELECT chave FROM lojas WHERE chave=?", (loja,)).fetchone()
        if cadastrada:
            loja = cadastrada["chave"]
        item = self.db.execute(
            "SELECT e.* FROM licencas e JOIN lojas l ON l.chave=e.loja "
            "WHERE e.loja=? AND l.ativa=1 ORDER BY e.expira_em DESC LIMIT 1", (loja,)).fetchone()
        if item is None:
            raise ErroCentral("Não há licença importada ou emitida para esta loja ativa.")
        validada = licenca.ler_licenca(item["codigo"])
        if validada["expira_em"] < date.fromisoformat(fmt.hoje()):
            raise ErroCentral("A licença mais recente já venceu; emita uma nova antes de publicar.")
        with self.db:
            self.db.execute("INSERT INTO config VALUES(?, 'S') ON CONFLICT(chave) DO UPDATE SET valor='S'",
                            (f"publicar_{item['id']}",))
            self._evento("publicacao_autorizada", f"{loja}; id={item['id']}")
        return item["id"]

    def sincronizar(self) -> dict:
        cliente = self._cliente()
        if self.config("recuperacao_pendente") == "S":
            resposta = cliente.chamar("GET", "/v1/central/lojas")
            remotas = resposta.get("lojas")
            if not isinstance(remotas, list):
                raise ErroCentral("Não foi possível recuperar os cadastros publicados na ponte.")
            validadas = []
            for item in remotas:
                if (not isinstance(item, dict) or not isinstance(item.get("nome"), str)
                        or not 1 <= len(item["nome"].strip()) <= 160 or type(item.get("ativa")) is not bool):
                    raise ErroCentral("Cadastro inválido devolvido pela ponte.")
                validadas.append((chave_loja(item.get("chave_loja")), item["nome"], int(item["ativa"])))
            with self.db:
                for chave, nome, ativa in validadas:
                    self.db.execute("INSERT INTO lojas VALUES(?,?,?) ON CONFLICT(chave) DO UPDATE "
                                    "SET nome=excluded.nome,ativa=excluded.ativa", (chave, nome, ativa))
                self._evento("cadastros_reconciliados", str(len(validadas)))
        for loja in self.lojas():
            cliente.chamar("PUT", "/v1/central/lojas/" + urllib.parse.quote(loja["chave"], safe=""),
                           {"nome": loja["nome"], "ativa": bool(loja["ativa"])})
        # Reconcilia antes de publicar, inclusive depois de restaurar backup antigo.
        self._guardar_estado(cliente.chamar("GET", "/v1/central/estado"))
        # Só a licença mais recente é publicada; importar histórico não migra lojas sozinho.
        pendentes = self.db.execute(
            "SELECT e.* FROM licencas e JOIN lojas l ON l.chave=e.loja WHERE e.publicada=0 "
            "AND (e.origem='central' OR EXISTS(SELECT 1 FROM config c WHERE "
            "c.chave='publicar_' || e.id AND c.valor='S')) AND l.ativa=1 AND e.expira_em=(SELECT MAX(expira_em) "
            "FROM licencas WHERE loja=e.loja) ORDER BY e.emitida_em,e.id").fetchall()
        for item in pendentes:
            cliente.chamar("POST", "/v1/central/licencas",
                           {"id": item["id"], "chave_loja": item["loja"], "codigo": item["codigo"]})
            with self.db:
                self.db.execute("UPDATE licencas SET publicada=1 WHERE id=?", (item["id"],))
                self._evento("licenca_publicada", f"{item['loja']}; id={item['id']}")
        estado = cliente.chamar("GET", "/v1/central/estado")
        self._guardar_estado(estado)
        self.configurar("recuperacao_pendente", "N")
        self.configurar("ultima_sincronizacao", fmt.agora())
        return estado

    def _guardar_estado(self, estado: dict) -> None:
        if not all(isinstance(estado.get(k), list) for k in ("caixas", "licencas", "solicitacoes")):
            raise ErroCentral("Estado incompleto devolvido pela ponte.")
        publicadas = []
        for item in estado["licencas"]:
            if not isinstance(item, dict):
                raise ErroCentral("Registro de licença inválido na ponte.")
            try:
                identificador = str(UUID(item["id"]))
                validada = licenca.ler_licenca(item["codigo"])
                chave = chave_loja(item["chave_loja"])
            except (KeyError, ValueError, TypeError, AttributeError):
                raise ErroCentral("Licença ilegível na ponte.") from None
            if not licenca.mesma_loja(chave, validada["loja"]):
                raise ErroCentral("A ponte devolveu licença de outra loja.")
            publicadas.append((identificador, chave, item["codigo"], validada))
        with self.db:
            for identificador, chave, codigo, validada in publicadas:
                loja = self.db.execute("SELECT chave FROM lojas WHERE chave=?", (chave,)).fetchone()
                if loja is None:
                    continue
                chave = loja["chave"]
                existente = self.db.execute("SELECT * FROM licencas WHERE id=?", (identificador,)).fetchone()
                if existente and (existente["codigo"] != codigo or existente["loja"] != chave):
                    raise ErroCentral("Conflito entre licença local e licença publicada.")
                if existente:
                    self.db.execute("UPDATE licencas SET publicada=1 WHERE id=?", (identificador,))
                else:
                    pelo_codigo = self.db.execute("SELECT id FROM licencas WHERE codigo=?", (codigo,)).fetchone()
                    if pelo_codigo:
                        self.db.execute("UPDATE licencas SET publicada=1 WHERE id=?", (pelo_codigo["id"],))
                    else:
                        self.db.execute("INSERT INTO licencas VALUES(?,?,?,?,?,1,'ponte')",
                                        (identificador, chave, codigo, validada["emitida_em"].isoformat(),
                                         validada["expira_em"].isoformat()))
            for tipo in ("caixas", "licencas", "solicitacoes"):
                self.db.execute(
                    "INSERT INTO retratos VALUES(?,?,?) ON CONFLICT(tipo) DO UPDATE "
                    "SET dados=excluded.dados,recebido_em=excluded.recebido_em",
                    (tipo, json.dumps(estado[tipo], ensure_ascii=False), fmt.agora()))

    def retrato(self, tipo: str) -> list[dict]:
        r = self.db.execute("SELECT dados FROM retratos WHERE tipo=?", (tipo,)).fetchone()
        return json.loads(r[0]) if r else []

    def backup(self, destino: Path) -> None:
        destino = Path(destino)
        if destino.resolve() == self.arquivo.resolve() or destino.exists():
            raise ErroCentral("Escolha um arquivo novo, diferente do banco da central.")
        with closing(sqlite3.connect(destino)) as copia:
            self.db.backup(copia)
            if copia.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ErroCentral("A verificação do backup falhou.")

    @staticmethod
    def restaurar(origem: Path, destino: Path) -> None:
        origem, destino = Path(origem), Path(destino)
        if destino.exists():
            raise ErroCentral("Restaure em um caminho novo, com a central encerrada.")
        try:
            with closing(sqlite3.connect(origem.resolve().as_uri() + "?mode=ro", uri=True)) as copia:
                if copia.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ErroCentral("Backup corrompido.")
                if copia.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ErroCentral("Versão de backup incompatível.")
                tabelas = {r[0] for r in copia.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"lojas", "licencas", "administradores", "confirmacoes", "eventos", "retratos", "config"} <= tabelas:
                    raise ErroCentral("O arquivo não é um backup completo da central.")
                destino.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(destino)) as nova:
                    copia.backup(nova)
                    with nova:
                        nova.execute("INSERT INTO config VALUES('recuperacao_pendente','S') "
                                     "ON CONFLICT(chave) DO UPDATE SET valor='S'")
        except sqlite3.Error:
            raise ErroCentral("Não foi possível restaurar o backup da central.") from None
