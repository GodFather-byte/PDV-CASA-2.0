"""Utilitários (manual ADM seção 7): backup, limpeza do movimento e programa de comunicação."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.controllers import notificacoes
from src.core import formatacao as fmt
from src.core import registro
from src.core.erros import ErroNegocio
from src.database import protecao
from src.database.conexao import RAIZ

log = logging.getLogger("pdv.backup")


class UtilitarioController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    # --------------------------------------------------------------- backup
    def pasta_backup(self) -> Path:
        escolhida = self.banco.cfg("pasta_backup").strip()
        return Path(escolhida) if escolhida else RAIZ / "Backup"

    def pasta_backup_extra(self) -> Path | None:
        """Segunda cópia (pendrive, outro disco ou pasta de rede): protege se o disco do caixa estragar."""
        escolhida = self.banco.cfg("pasta_backup_extra").strip()
        return Path(escolhida) if escolhida else None

    def pastas_backup(self) -> list[Path]:
        return [p for p in (self.pasta_backup(), self.pasta_backup_extra()) if p is not None]

    def backup(self, manter: int = 60) -> str:
        """Cópia consistente do banco com data e hora no nome, conferida logo depois de gravada. Mantém os `manter`
        mais novos. Se houver pasta extra configurada, grava lá também; falha só na extra não cancela o backup."""
        pasta = self.pasta_backup()
        pasta.mkdir(parents=True, exist_ok=True)
        nome = f"loja_offline-{fmt.agora().replace(':', '').replace(' ', '-')}.db"
        destino = pasta / nome
        self.banco.copiar_para(str(destino))
        problema = protecao.verificar_arquivo(destino)
        if problema:                       # nunca deixa uma cópia ruim ocupar o lugar de uma boa
            destino.unlink(missing_ok=True)
            raise ErroNegocio(f"O backup saiu danificado e foi descartado ({problema}). Verifique o disco.")
        self.banco.cfg_set("ultimo_backup", fmt.agora())
        self.banco.log("backup", str(destino), self.operador_id)
        if self.banco.caminho != ":memory:":
            protecao.registrar_pasta(self.banco.caminho, pasta)
        self._podar(pasta, manter)
        extra = self.pasta_backup_extra()
        erro_extra = ""
        if extra is not None:
            try:
                extra.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(destino, extra / nome)
                if self.banco.caminho != ":memory:":
                    protecao.registrar_pasta(self.banco.caminho, extra)
                self._podar(extra, manter)
            except OSError as e:
                erro_extra = f"não foi possível gravar na pasta extra ({e})"
                log.warning("Backup extra falhou: %s", e)
        self.banco.cfg_set("backup_extra_erro", erro_extra)
        if self.banco.cfg("backup_externo_pasta"):
            try:
                self.backup_externo(origem=destino, manter=manter)
            except (OSError, ValueError, ErroNegocio) as e:
                self.banco.cfg_set("backup_externo_erro", f"{fmt.agora()} {e}"[:300])
                log.error("Backup externo criptografado falhou: %s", e)
                notificacoes.avisar(self.banco, "backup", "backup_externo_falhou", str(e))
        return str(destino)

    def _cofre_backup(self) -> Path:
        if self.banco.caminho == ":memory:":
            raise ErroNegocio("Configure o backup automático em um banco salvo no computador.")
        return Path(self.banco.caminho + ".backup.key")

    def configurar_backup_externo(self, pasta: str, senha: str) -> None:
        from src.core import backup_seguro
        if not pasta.strip():
            raise ErroNegocio("Escolha a pasta sincronizada para o backup externo.")
        destino = Path(pasta).expanduser().resolve()
        if any(destino == local.resolve() for local in self.pastas_backup()):
            raise ErroNegocio("Escolha uma pasta exclusiva para os arquivos criptografados, diferente dos backups locais/extra.")
        destino.mkdir(parents=True, exist_ok=True)
        try:
            backup_seguro.guardar_senha(self._cofre_backup(), senha)
        except ValueError as e:
            raise ErroNegocio(str(e)) from e
        with self.banco.transacao():
            self.banco.cfg_set("backup_externo_pasta", str(destino))
            self.banco.cfg_set("backup_externo_ultimo", "")
            self.banco.cfg_set("backup_externo_verificado_em", "")
            self.banco.cfg_set("backup_externo_erro", "")
            self.banco.log("backup_externo_configurado", str(destino), self.operador_id)

    def desativar_backup_externo(self) -> None:
        cofre = self._cofre_backup()
        with self.banco.transacao():
            self.banco.cfg_set("backup_externo_pasta", "")
            self.banco.cfg_set("backup_externo_erro", "")
            self.banco.log("backup_externo_desativado", "", self.operador_id)
        cofre.unlink(missing_ok=True)

    def backup_externo(self, senha: str | None = None, origem: Path | None = None, manter: int = 60) -> str:
        from src.core import backup_seguro
        if manter < 1:
            raise ErroNegocio("Mantenha pelo menos um backup externo.")
        pasta = self.banco.cfg("backup_externo_pasta").strip()
        if not pasta:
            raise ErroNegocio("Configure a pasta do backup externo antes de gerar a cópia.")
        try:
            senha = senha if senha is not None else backup_seguro.ler_senha(self._cofre_backup())
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            nome = f"loja_offline-seguro-{fmt.agora().replace(':', '').replace(' ', '-')}-{uuid4().hex}.pdvbkp"
            arquivo = destino / nome
            preparado = destino / f".{nome}.verificando"
            try:
                with tempfile.TemporaryDirectory(prefix="willpdv_backup_") as temporarios:
                    copia = Path(temporarios) / "copia.db"
                    if origem is None:
                        self.banco.copiar_para(str(copia))
                    else:
                        copia = Path(origem)
                    if not protecao.backup_valido(copia):
                        raise ErroNegocio("A cópia local não é um backup válido do PDV.")
                    backup_seguro.criptografar(copia, preparado, senha)
                    self.verificar_backup_externo(str(preparado), senha)
                    os.replace(preparado, arquivo)
            finally:
                preparado.unlink(missing_ok=True)
        except (OSError, ValueError, ErroNegocio) as e:
            self.banco.cfg_set("backup_externo_erro", f"{fmt.agora()} {e}"[:300])
            log.error("Não foi possível gerar o backup externo: %s", e)
            raise ErroNegocio(f"Backup externo não concluído: {e}") from e
        self.banco.cfg_set("backup_externo_ultimo", fmt.agora())
        self.banco.cfg_set("backup_externo_verificado_em", fmt.agora())
        self.banco.cfg_set("backup_externo_erro", "")
        self.banco.log("backup_externo_verificado", str(arquivo), self.operador_id)
        for antigo in sorted(destino.glob("loja_offline-seguro-*.pdvbkp"),
                             key=lambda p: (p == arquivo, p.name), reverse=True)[manter:]:
            try:
                antigo.unlink()
            except OSError as e:
                log.warning("Não foi possível remover backup externo antigo %s: %s", antigo.name, e)
        return str(arquivo)

    def verificar_backup_externo(self, caminho: str, senha: str) -> None:
        from src.core import backup_seguro
        try:
            with tempfile.TemporaryDirectory(prefix="willpdv_verificar_") as pasta:
                destino = Path(pasta) / "recuperado.db"
                backup_seguro.descriptografar(caminho, destino, senha)
                if not protecao.backup_valido(destino):
                    raise ValueError("O conteúdo recuperado não é um banco válido do PDV.")
        except (OSError, ValueError) as e:
            raise ErroNegocio(f"Não foi possível verificar o backup: {e}") from e

    def pedir_restauracao_externa(self, caminho: str, senha: str) -> None:
        from src.core import backup_seguro
        from src.database import esquema
        import sqlite3
        try:
            with tempfile.TemporaryDirectory(prefix="willpdv_recuperar_") as pasta:
                recuperado = Path(pasta) / "recuperado.db"
                backup_seguro.descriptografar(caminho, recuperado, senha)
                if not protecao.backup_valido(recuperado):
                    raise ValueError("O conteúdo recuperado não é um banco válido do PDV.")
                conexao = sqlite3.connect(recuperado)
                try:
                    versao = conexao.execute("PRAGMA user_version").fetchone()[0]
                finally:
                    conexao.close()
                if versao > esquema.VERSAO_ESQUEMA:
                    raise ValueError("Este backup exige uma versão mais recente do PDV.")
                destino = self.pasta_backup()
                destino.mkdir(parents=True, exist_ok=True)
                local = destino / f"loja_offline-recuperado-{uuid4().hex}.db"
                shutil.copyfile(recuperado, local)
                try:
                    self.pedir_restauracao(str(local))
                except BaseException:
                    local.unlink(missing_ok=True)
                    raise
        except (OSError, ValueError) as e:
            raise ErroNegocio(f"Não foi possível recuperar o backup externo: {e}") from e

    @staticmethod
    def _podar(pasta: Path, manter: int) -> None:
        for p in sorted(pasta.glob(protecao.PADRAO_BACKUP), key=lambda p: p.name, reverse=True)[manter:]:
            try:
                p.unlink()
            except OSError:
                pass

    def backup_automatico(self, motivo: str, minimo_min: int = 0) -> str | None:
        """Backup sem o operador pedir (troca de turno, saída, início). NUNCA levanta erro: devolve o caminho ou None, e
        guarda o último problema em `backup_erro` para o painel avisar. `minimo_min` evita repetir um backup recente."""
        if minimo_min and (idade := self.idade_backup_horas()) is not None and idade * 60 < minimo_min:
            return None
        try:
            caminho = self.backup()
        except Exception as e:  # noqa: BLE001 - o backup nunca pode impedir o caixa de trabalhar
            log.error("Backup automático (%s) falhou: %s", motivo, e)
            self.banco.cfg_set("backup_erro", f"{fmt.agora()} {e}"[:300])
            notificacoes.avisar(self.banco, "backup", "backup_falhou", str(e))
            return None
        self.banco.cfg_set("backup_erro", "")
        log.info("Backup automático (%s): %s", motivo, caminho)
        return caminho

    def idade_backup_horas(self) -> float | None:
        ultimo = self.ultimo_backup()
        if not ultimo:
            return None
        try:
            return max((datetime.fromisoformat(fmt.agora()) - datetime.fromisoformat(ultimo)).total_seconds() / 3600, 0.0)
        except ValueError:
            return None

    def situacao_backup(self, limite_horas: int = 24) -> tuple[str, str]:
        """(nível, texto) para o painel: 'ok', 'aviso' (atrasado, com erro ou sem cópia extra que falhou) ou 'sem'."""
        erro = self.banco.cfg("backup_erro")
        idade = self.idade_backup_horas()
        if idade is None:
            externo = self.banco.cfg("backup_externo_ultimo")
            if self.banco.cfg("backup_externo_pasta") and externo:
                return "aviso", ("Nenhum backup local registrado. Última cópia externa verificada: "
                                 f"{fmt.fmt_datahora(externo)}; confira o envio no sincronizador.")
            return "sem", "ATENÇÃO: nenhum backup feito ainda. Faça em Utilitários > Backup de dados."
        quando = fmt.fmt_datahora(self.ultimo_backup())
        if erro:
            return "aviso", f"ATENÇÃO: o último backup automático falhou. Último que deu certo: {quando}."
        if idade >= limite_horas:
            return "aviso", f"ATENÇÃO: último backup há {int(idade // 24)} dia(s) e {int(idade % 24)} h ({quando})."
        extra_erro = self.banco.cfg("backup_extra_erro")
        if extra_erro:
            return "aviso", f"Último backup: {quando}, mas {extra_erro}."
        if self.banco.cfg("backup_externo_pasta"):
            externo = self.banco.cfg("backup_externo_ultimo")
            if self.banco.cfg("backup_externo_erro"):
                return "aviso", f"Backup local: {quando}. A cópia externa criptografada falhou; verifique em Utilitários."
            if not externo:
                return "aviso", f"Backup local: {quando}. Ainda não há cópia externa criptografada verificada."
            try:
                idade_externa = (datetime.fromisoformat(fmt.agora()) - datetime.fromisoformat(externo)).total_seconds() / 3600
            except ValueError:
                return "aviso", "A data do backup externo é inválida; gere uma nova cópia."
            if idade_externa >= limite_horas:
                return "aviso", f"Backup local: {quando}. A cópia externa criptografada está atrasada."
            return "ok", f"Backup local: {quando}. Cópia externa verificada; envio online depende do sincronizador da pasta."
        return "ok", f"Último backup: {quando}"

    def listar_backups(self) -> list[Path]:
        return protecao.listar_backups(self.pastas_backup())

    def pedir_restauracao(self, backup: str) -> None:
        """Marca a restauração para o próximo início do programa e antes guarda uma cópia do banco de agora."""
        if not protecao.backup_valido(backup):
            raise ErroNegocio("O backup escolhido está danificado ou não é um banco do PDV.")
        self.backup()                        # rede de segurança: a situação de agora também fica guardada
        self.banco.log("restauracao_pedida", str(backup), self.operador_id)
        protecao.pedir_restauracao(self.banco.caminho, backup)

    def pacote_suporte(self) -> str:
        return str(registro.pacote_suporte(self.pasta_backup().parent / "Suporte"))

    def ultimo_backup(self) -> str | None:
        return self.banco.cfg("ultimo_backup") or None

    # -------------------------------------------------------------- limpeza
    def limpar_movimento(self, antes_de: str) -> dict:
        """Apaga vendas e movimentos ANTERIORES à data (o período apagado termina no dia anterior).

        Salvaguardas: faz backup antes e não apaga o dia de hoje em diante."""
        data = fmt.para_data_iso(antes_de)
        if not data:
            raise ErroNegocio("Informe a data limite (dd/mm/aaaa).")
        if data > fmt.hoje():
            raise ErroNegocio("A data limite não pode ser futura.")
        if data == fmt.hoje():
            raise ErroNegocio("A limpeza apaga até o dia anterior à data informada; use no máximo a data de hoje "
                              "menos 1 dia para preservar o movimento atual.")
        alvo = ("status IN ('fechada','cancelada') AND date(COALESCE(fechada_em, aberta_em)) < ?")
        copia = self.backup()
        with self.banco.transacao():
            # A numeração dos cupons continua de onde parou (turno_controller.proximo_cupom), mesmo sem as vendas apagadas.
            self.banco.cfg_set("ultimo_cupom_emitido", self.banco.valor(
                "SELECT MAX(COALESCE(MAX(cupom), 0), ?) FROM vendas", (self.banco.cfg_int("ultimo_cupom_emitido", 0),), 0))
            ids = [r[0] for r in self.banco.todos(f"SELECT id FROM vendas WHERE {alvo}", (data,))]
            for i in range(0, len(ids), 500):
                lote = ids[i:i + 500]
                marcas = ",".join("?" * len(lote))
                self.banco.executar(f"UPDATE caderneta SET venda_id = NULL WHERE venda_id IN ({marcas})", lote)
                self.banco.executar(f"UPDATE repiques SET venda_id = NULL WHERE venda_id IN ({marcas})", lote)
                self.banco.executar(f"DELETE FROM vendas WHERE id IN ({marcas})", lote)
            # Fica o turno que ainda tem venda ou que recebeu o adiantamento de uma conta fechada depois do corte.
            turnos = [r[0] for r in self.banco.todos(
                """SELECT t.id FROM turnos t WHERE t.status = 'fechado' AND date(t.aberto_em) < ?
                   AND NOT EXISTS (SELECT 1 FROM vendas v WHERE v.turno_id = t.id)
                   AND NOT EXISTS (SELECT 1 FROM pagamentos_venda p WHERE p.turno_id = t.id)""", (data,))]
            comissoes = 0
            for t in turnos:
                # Comissões das garotas: a paga aponta para a sangria que vai ser apagada; as pagas e canceladas saem com o
                # turno, mas a PENDENTE é dinheiro devido e fica (só perde o turno).
                self.banco.executar("UPDATE comissoes_garotas SET movimento_id = NULL WHERE movimento_id IN "
                                    "(SELECT id FROM movimentos_caixa WHERE turno_id = ?)", (t,))
                self.banco.executar("UPDATE comissoes_garotas SET turno_id = NULL WHERE turno_id = ? AND status = 'pendente'", (t,))
                self.banco.executar("UPDATE comissoes_garotas SET pago_turno_id = NULL WHERE pago_turno_id = ?", (t,))
                comissoes += self.banco.executar(
                    "DELETE FROM comissoes_garotas WHERE turno_id = ? AND status <> 'pendente'", (t,)).rowcount
                self.banco.executar("DELETE FROM acertos_garotas WHERE turno_id = ?", (t,))      # o acerto sai com o turno e a sangria dele
                self.banco.executar("DELETE FROM movimentos_caixa WHERE turno_id = ?", (t,))
                self.banco.executar("DELETE FROM repiques WHERE turno_id = ?", (t,))
                self.banco.executar("DELETE FROM turnos WHERE id = ?", (t,))
            movs = self.banco.executar("DELETE FROM movimentos_estoque WHERE date(criado_em) < ?", (data,)).rowcount
            logs = self.banco.executar("DELETE FROM log_eventos WHERE date(quando) < ?", (data,)).rowcount
            self.banco.log("limpeza_movimento", f"até {data}: {len(ids)} vendas, {len(turnos)} turnos", self.operador_id)
        return {"vendas": len(ids), "turnos": len(turnos), "movimentos_estoque": movs, "logs": logs, "comissoes": comissoes,
                "backup": copia}

    # ------------------------------------------------------ excluir todos os produtos
    def resumo_exclusao_produtos(self) -> dict:
        """Quantidade removida do cadastro; o histórico não ocupa códigos comerciais."""
        total = self.banco.valor("SELECT COUNT(*) FROM produtos", (), 0)
        abertas = self.banco.valor(
            """SELECT COUNT(*) FROM vendas v WHERE v.status IN ('aberta','conta_enviada')
               AND EXISTS (SELECT 1 FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0)""", (), 0)
        return {"total": total, "excluidos": total, "guardados": 0, "vendas_abertas": abertas}

    def excluir_todos_produtos(self) -> dict:
        """Remove o catálogo após backup, preservando vendas e movimentos no histórico."""
        r = self.resumo_exclusao_produtos()
        if not r["total"]:
            raise ErroNegocio("Não há produtos cadastrados.")
        if r["vendas_abertas"]:
            raise ErroNegocio(f"Há {r['vendas_abertas']} venda(s), mesa(s) ou comanda(s) abertas com itens. Feche ou cancele "
                              "antes de excluir os produtos.")
        copia = self.backup()
        with self.banco.transacao():
            if self.resumo_exclusao_produtos()["vendas_abertas"]:
                raise ErroNegocio("Há vendas abertas com itens. Feche ou cancele antes de excluir os produtos.")
            if self.banco.valor("""SELECT 1 FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                                   JOIN produtos p ON p.id = i.produto_id WHERE l.tipo = 'pedido' LIMIT 1"""):
                raise ErroNegocio("Há produtos em pedidos de compra. Remova ou conclua os pedidos antes de excluir.")
            from src.controllers.produto_controller import ProdutoController
            produtos = ProdutoController(self.banco)
            for (pid,) in self.banco.todos("SELECT id FROM produtos"):
                self.banco.executar(
                    "UPDATE produtos_historico SET custo_cent = ?, ativo = 0, excluido_em = ? WHERE id = ?",
                    (produtos.custo(pid), fmt.agora(), pid))
            self.banco.executar("DELETE FROM composicoes")
            self.banco.executar("DELETE FROM produtos")
            self.banco.log("excluir_todos_produtos", f"{r['excluidos']} excluídos do cadastro; histórico preservado",
                           self.operador_id)
        return {"excluidos": r["excluidos"], "guardados": r["guardados"], "backup": copia}

    # ------------------------------------------------------ comunicação
    def abrir_programa_comunicacao(self) -> None:
        """Abre o programa configurado (ex.: TeamViewer). Sem configuração, abre a Calculadora do Windows."""
        caminho = self.banco.cfg("programa_comunicacao").strip()
        try:
            if caminho:
                if not os.path.exists(caminho):
                    raise ErroNegocio(f"Programa não encontrado: {caminho}")
                subprocess.Popen([caminho])
            elif os.name == "nt":
                subprocess.Popen(["calc.exe"])
            else:
                raise ErroNegocio("Configure o programa de comunicação em Configurações > Configurações.")
        except OSError as e:
            raise ErroNegocio(f"Não foi possível abrir o programa: {e}") from e
