"""Estado compartilhado da sessão: banco, operador logado e acesso aos controladores."""
from __future__ import annotations

from src.controllers.acesso_controller import AcessoController, Operador
from src.controllers.auditoria_controller import AuditoriaController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.caderneta_controller import CadernetaController
from src.controllers.caixa_controller import CaixaController
from src.controllers.comissao_controller import ComissaoController
from src.controllers.config_controller import ConfigController
from src.controllers.contas_controller import ContasController
from src.controllers.entrega_controller import EntregaController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.perfil_controller import PerfilController
from src.controllers.preparo_controller import PreparoController
from src.controllers.produto_controller import ProdutoController
from src.controllers.quartos_controller import QuartosController
from src.controllers.relatorio_controller import RelatorioController
from src.controllers.telegram_controller import TelegramController
from src.controllers.turno_controller import TurnoController
from src.controllers.utilitario_controller import UtilitarioController
from src.hardware.dispositivos import Balanca, Gaveta
from src.hardware.impressora_termica import ImpressoraTermica


class Contexto:
    def __init__(self, banco, operador: Operador | None = None):
        self.banco = banco
        self.operador = operador
        self.acesso = AcessoController(banco)
        self.cadastros = CadastroController(banco)
        self.config = ConfigController(banco)
        self.produtos = ProdutoController(banco)
        self.turnos = TurnoController(banco)
        self.relatorios = RelatorioController(banco)
        self.impressao = ImpressaoController(banco)
        self.caderneta = CadernetaController(banco)
        self.comissoes = ComissaoController(banco)
        self.telegram = TelegramController(banco)
        self.ao_mudar_tema = None          # a janela principal põe aqui o que refaz o visual quando o operador troca claro/escuro

    @property
    def operador(self) -> Operador | None:
        return self._operador

    @operador.setter
    def operador(self, operador: Operador | None) -> None:
        self.banco.definir_operador_auditoria(operador.id if operador else None)
        self._operador = operador

    @property
    def auditoria(self) -> AuditoriaController:
        return AuditoriaController(self.banco, self.operador)

    @property
    def operador_id(self) -> int | None:
        return self.operador.id if self.operador else None

    # Controladores que gravam o operador responsável: criados na hora com o operador atual.
    @property
    def caixa(self) -> CaixaController:
        return CaixaController(self.banco, self.operador_id)

    @property
    def entregas(self) -> EntregaController:
        return EntregaController(self.banco, self.caixa)

    @property
    def estoque(self) -> EstoqueController:
        return EstoqueController(self.banco, self.operador_id)

    @property
    def contas(self) -> ContasController:
        return ContasController(self.banco, self.operador_id)

    @property
    def utilitarios(self) -> UtilitarioController:
        return UtilitarioController(self.banco, self.operador_id)

    @property
    def preparo(self) -> PreparoController:
        return PreparoController(self.banco, self.operador_id)

    @property
    def quartos(self) -> QuartosController:
        return QuartosController(self.banco, self.operador_id)

    @property
    def perfil(self) -> PerfilController:
        return PerfilController(self.banco, self.operador_id)

    def balanca(self) -> Balanca:
        m = self.config.maquina()
        return Balanca(m["balanca"], m["balanca_porta"])

    def gaveta(self) -> Gaveta:
        m = self.config.maquina()
        return Gaveta(bool(m["gaveta"]), ImpressoraTermica.da_maquina(m))

    def pode(self, modulo: str) -> bool:
        return self.operador is not None and self.acesso.pode(self.operador, modulo)
