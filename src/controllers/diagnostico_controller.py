"""Diagnóstico central dos equipamentos do caixa: impressora, gaveta, balança e leitor de código de barras.

Regras das telas Qt:
- `resumo()` e `avaliar_leitura()` só leem a configuração e o cadastro: nunca acionam equipamento.
- `verificar_impressora()` consulta o Windows (lista de impressoras, spooler) sem imprimir nada.
- Os testes ativos (`testar_impressora`, `testar_gaveta`, `ler_balanca`) só rodam com o operador que a tela capturou
  ANTES da confirmação: a permissão `cfg_maquinas` é reconsultada no banco depois do diálogo e, se a sessão mudou,
  nada é enviado.
- "Comando enviado" não é "funcionou": o resultado só vira confirmado quando o operador diz que viu o papel sair,
  a gaveta abrir ou o peso bater com o visor (`confirmar`). Tudo vai para o log de eventos.
- Nenhum teste lança venda, mexe em estoque, caixa ou turno.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, replace

from src.controllers import impressao_assistente as assistente
from src.core.erros import ErroNegocio, ErroPermissao
from src.hardware.dispositivos import DispositivoIndisponivel

DISPOSITIVOS = {"impressora": "Impressora", "gaveta": "Gaveta", "balanca": "Balança", "leitor": "Leitor de código"}

ESTADOS = {
    "configurado": "Configurado (ainda não testado)",
    "indisponivel": "Indisponível",
    "erro": "Erro",
    "enviado": "Comando enviado: aguardando conferência",
    "lido": "Leitura recebida: aguardando conferência",
    "confirmado": "Confirmado pelo operador",
    "nao_confirmado": "Não confirmado pelo operador",
}


@dataclass(frozen=True)
class Resultado:
    dispositivo: str
    estado: str
    mensagem: str
    valor: object = None

    @property
    def rotulo(self) -> str:
        return f"{DISPOSITIVOS[self.dispositivo]}: {ESTADOS[self.estado]}"

    @property
    def aguarda_conferencia(self) -> bool:
        return self.estado in ("enviado", "lido")


def gtin_valido(codigo: str) -> bool:
    """Confere o dígito verificador de EAN-8, UPC-A (12), EAN-13 e GTIN-14."""
    if not codigo.isdigit() or len(codigo) not in (8, 12, 13, 14):
        return False
    corpo, dv = codigo[:-1], int(codigo[-1])
    soma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(corpo)))
    return (10 - soma % 10) % 10 == dv


class DiagnosticoController:
    def __init__(self, ctx):
        self.ctx = ctx
        self.banco = ctx.banco

    # ------------------------------------------------------------ acesso
    def exigir(self) -> int:
        """Reconsulta o operador no banco e exige `cfg_maquinas`. Devolve o id do operador."""
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para diagnosticar os equipamentos.")
        cadastro = self.ctx.cadastros.obter("operadores", operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(operador_id), "cfg_maquinas")
        return operador_id

    def _conferir_sessao(self, operador_id: int) -> int:
        atual = self.exigir()
        if atual != operador_id:
            raise ErroPermissao("A sessão mudou durante a confirmação. Nada foi enviado; confirme novamente.")
        return atual

    def _log(self, evento: str, detalhe: str, operador_id: int | None) -> None:
        try:
            self.banco.log(f"diagnostico_{evento}", detalhe, operador_id)
        except Exception:  # noqa: BLE001 - o log não pode esconder o resultado do teste
            from src.core import registro
            registro.registrar_excecao(*sys.exc_info(), origem="diagnostico_log")

    # ------------------------------------------------------------ só leitura
    def resumo(self) -> dict[str, Resultado]:
        """O que está configurado em cada equipamento. Não aciona nada."""
        m = self.ctx.config.maquina()
        return {"impressora": self._resumo_impressora(m), "gaveta": self._resumo_gaveta(),
                "balanca": self._resumo_balanca(), "leitor": self._resumo_leitor(m)}

    def _resumo_impressora(self, m: dict) -> Resultado:
        imp = self.ctx.impressao.impressora_termica()
        modo = m.get("modo_impressao") or "tela"
        if not imp.configurada:
            return Resultado("impressora", "indisponivel",
                             f"Nenhuma impressora térmica configurada (modo de impressão: {modo}). "
                             "Use Máquinas ou o Assistente de impressora.")
        texto = f"Térmica por {imp.conexao}: {imp.endereco or '(sem endereço)'}; {imp.colunas} colunas, {imp.codepage}."
        if modo != "termica":
            texto += f" Atenção: o modo de impressão está em '{modo}', então os cupons não vão para ela."
        return Resultado("impressora", "configurado", texto)

    def _resumo_gaveta(self) -> Resultado:
        g = self.ctx.gaveta()
        if g.automatica:
            return Resultado("gaveta", "configurado",
                             f"Abre pelo pulso da impressora térmica (pino {g.impressora.pino_gaveta}).")
        if g.instalada:
            return Resultado("gaveta", "indisponivel",
                             "Gaveta marcada como instalada, mas não ligada à impressora térmica: abre só com a chave.")
        return Resultado("gaveta", "indisponivel", "Nenhuma gaveta configurada.")

    def _resumo_balanca(self) -> Resultado:
        b = self.ctx.balanca()
        if not b.configurada:
            return Resultado("balanca", "indisponivel", "Balança não configurada ou sem porta COM definida.")
        if importlib.util.find_spec("serial") is None:
            return Resultado("balanca", "indisponivel",
                             f"{b.modelo} na porta {b.porta}, mas falta o pyserial (pip install pyserial).")
        return Resultado("balanca", "configurado", f"{b.modelo} na porta {b.porta}.")

    @staticmethod
    def _resumo_leitor(m: dict) -> Resultado:
        if m.get("leitor_optico"):
            return Resultado("leitor", "configurado",
                             "Leitor marcado. Ele funciona como teclado: passe um código no campo de teste.")
        return Resultado("leitor", "configurado",
                         "Leitor não marcado em Máquinas; o campo de teste funciona assim mesmo.")

    def verificar_impressora(self, **consulta) -> list[assistente.Achado]:
        """Diagnóstico do assistente (configuração, Windows, fila do PDV) sem imprimir."""
        operador_id = self.exigir()
        achados = assistente.diagnosticar(self.banco, **consulta)
        erros = [a.texto for a in achados if a.nivel == "erro"]
        self._log("impressora_verificada", "; ".join(erros) or "sem erros", operador_id)
        return achados

    def avaliar_leitura(self, codigo: str) -> Resultado:
        """Explica o que o leitor mandou. Só consulta o cadastro: não vende nem mexe em estoque."""
        bruto = codigo or ""
        texto = bruto.strip()
        if not texto:
            return Resultado("leitor", "erro", "Nada foi lido. Clique no campo de teste e passe o código no leitor.")
        partes = [f"Recebido: {texto} ({len(texto)} caractere(s))."]
        if bruto != texto:
            partes.append("Vieram espaços ou tabulação junto: confira o sufixo do leitor (o certo é Enter).")
        if texto.isdigit() and len(texto) in (8, 12, 13, 14):
            partes.append("Dígito verificador correto." if gtin_valido(texto)
                          else "Dígito verificador NÃO confere: leitura incompleta ou etiqueta danificada.")
        produto = self.ctx.produtos.buscar_codigo(texto, apenas_venda=False)
        partes.append(f"Produto cadastrado: {produto['nome']}." if produto else "Nenhum produto com este código.")
        partes.append("Nenhuma venda foi lançada.")
        return Resultado("leitor", "lido", " ".join(partes), valor=texto)

    # ------------------------------------------------------------ testes ativos (depois da confirmação)
    def _falha(self, dispositivo: str, erro: BaseException, operador_id: int, inesperado: bool = False) -> Resultado:
        if inesperado:
            from src.core import registro
            registro.registrar_excecao(type(erro), erro, erro.__traceback__, origem=f"diagnostico_{dispositivo}")
        texto = str(erro) or type(erro).__name__
        self._log(f"{dispositivo}_erro", texto, operador_id)
        return Resultado(dispositivo, "erro", texto)

    def testar_impressora(self, operador_id: int) -> Resultado:
        self._conferir_sessao(operador_id)
        imp = self.ctx.impressao.impressora_termica()
        if not imp.configurada:
            self._log("impressora_indisponivel", "sem impressora térmica", operador_id)
            return Resultado("impressora", "indisponivel",
                             "Nenhuma impressora térmica configurada: nada foi enviado.")
        try:
            self.ctx.impressao.imprimir_teste()
        except (ErroNegocio, OSError) as erro:
            return self._falha("impressora", erro, operador_id)
        except Exception as erro:  # noqa: BLE001 - driver/sistema: mostrar e registrar, nunca derrubar a tela
            return self._falha("impressora", erro, operador_id, inesperado=True)
        self._log("impressora_enviado", f"{imp.conexao}:{imp.endereco}", operador_id)
        return Resultado("impressora", "enviado",
                         f"Página de teste enviada para {imp.endereco or imp.conexao}. Confira se o papel saiu, "
                         "com acentos e corte.")

    def testar_gaveta(self, operador_id: int) -> Resultado:
        self._conferir_sessao(operador_id)
        gaveta = self.ctx.gaveta()
        if not gaveta.automatica:
            texto = self._resumo_gaveta().mensagem + " Nada foi enviado."
            self._log("gaveta_indisponivel", texto, operador_id)
            return Resultado("gaveta", "indisponivel", texto)
        try:
            gaveta.abrir()
        except (DispositivoIndisponivel, ErroNegocio, OSError) as erro:
            return self._falha("gaveta", erro, operador_id)
        except Exception as erro:  # noqa: BLE001
            return self._falha("gaveta", erro, operador_id, inesperado=True)
        self._log("gaveta_enviado", "pulso enviado", operador_id)
        return Resultado("gaveta", "enviado",
                         "Pulso de abertura enviado. Confira se a gaveta abriu. Nenhum movimento de caixa foi lançado.")

    def ler_balanca(self, operador_id: int) -> Resultado:
        self._conferir_sessao(operador_id)
        resumo = self._resumo_balanca()
        if resumo.estado == "indisponivel":
            self._log("balanca_indisponivel", resumo.mensagem, operador_id)
            return replace(resumo, mensagem=resumo.mensagem + " Nada foi lido.")
        try:
            peso = float(self.ctx.balanca().ler_peso())
        except (DispositivoIndisponivel, ErroNegocio, OSError, ValueError) as erro:
            return self._falha("balanca", erro, operador_id)
        except Exception as erro:  # noqa: BLE001
            return self._falha("balanca", erro, operador_id, inesperado=True)
        peso = round(peso, 3)
        self._log("balanca_lido", f"{peso:.3f} kg", operador_id)
        return Resultado("balanca", "lido",
                         f"A balança informou {peso:.3f} kg. Compare com o visor dela; nada foi lançado.", valor=peso)

    def confirmar(self, resultado: Resultado, ok: bool, operador_id: int) -> Resultado:
        """Registra o que o operador VIU (papel saiu, gaveta abriu, peso confere, produto certo)."""
        if not resultado.aguarda_conferencia:
            raise ErroNegocio("Este resultado não aguarda conferência.")
        self._conferir_sessao(operador_id)
        self._log(f"{resultado.dispositivo}_{'confirmado' if ok else 'nao_confirmado'}",
                  "" if resultado.valor is None else str(resultado.valor), operador_id)
        if ok:
            return replace(resultado, estado="confirmado",
                           mensagem=resultado.mensagem + " O operador confirmou o resultado.")
        return replace(resultado, estado="nao_confirmado",
                       mensagem=resultado.mensagem + " O operador NÃO confirmou: confira cabo, energia e configuração.")
