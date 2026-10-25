"""Configurações (manual ADM seção 8): dados da loja, parâmetros operacionais e máquinas.

As listas `CAMPOS_*` descrevem os formulários; a interface os desenha sem código extra."""
from __future__ import annotations

import re

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.sementes import CONFIG_PADRAO, aplicar_padrao_telegram_23h

# (chave, rótulo, tipo[texto|int|decimal|sn|escolha], seção, opções)
CAMPOS_LOJA = [
    ("razao_social", "Razão social", "texto"), ("nome_fantasia", "Nome fantasia", "texto"),
    ("slogan", "Slogan (impresso no cupom)", "texto"), ("cnpj", "CNPJ", "texto"), ("ie", "Inscrição estadual", "texto"),
    ("endereco", "Endereço", "texto"), ("complemento", "Complemento", "texto"), ("bairro", "Bairro", "texto"),
    ("cidade", "Cidade", "texto"), ("uf", "UF", "texto"), ("cep", "CEP", "texto"),
    ("telefone", "Telefone", "texto"), ("email", "E-mail", "texto"),
    ("logotipo", "Logotipo (PNG/JPG/JPEG/BMP, até 5 MiB)", "texto"),
]

CAMPOS_MAQUINA = [
    ("terminal", "Nº do terminal", "int"), ("nome_computador", "Nome do computador", "texto"),
    ("descricao", "Descrição", "texto"),
    ("modo_impressao", "Impressão de cupons e relatórios", "escolha",
     [("tela", "Mostrar na tela"), ("termica", "Impressora térmica (ESC/POS)"),
      ("windows", "Impressora padrão do Windows"), ("arquivo", "Salvar em arquivo")]),
    ("colunas_fita", "Colunas da fita (58mm = 32, 80mm = 48)", "int"),
    ("impressora_termica_conexao", "Impressora térmica: conexão", "escolha",
     [("rede", "Rede (TCP/IP, porta 9100)"), ("serial", "Serial (COM)"),
      ("spooler", "Impressora do Windows (USB ou instalada)"), ("arquivo", "Arquivo/dispositivo"), ("nenhuma", "Nenhuma")]),
    ("impressora_termica_endereco", "Impressora térmica: endereço (IP:porta, COM1 ou COM1:19200, nome no Windows ou caminho)", "texto"),
    ("impressora_termica_codepage", "Impressora térmica: página de código", "escolha",
     [("cp850", "CP850 (padrão, português)"), ("cp860", "CP860 (português)"),
      ("cp1252", "Windows-1252"), ("cp437", "CP437"), ("ascii", "ASCII (sem acentos)")]),
    ("impressora_termica_cortar", "Impressora térmica: cortar o papel", "sn"),
    ("impressora_termica_gaveta", "Gaveta ligada à impressora térmica", "sn"),
    ("impressora_termica_pino", "Pino da gaveta (0 ou 1)", "int"),
    ("impressora_termica_logotipo", "Imprimir o logotipo da loja no cupom (Configurações > Loja)", "sn"),
    ("impressora_remota_conexao", "Impressora remota (cozinha/bar): conexão", "escolha",
     [("pasta", "Pasta de arquivos"), ("rede", "Rede (TCP/IP)"),
      ("spooler", "Impressora do Windows (USB ou instalada)"), ("nenhuma", "Nenhuma")]),
    ("impressora_remota_pasta", "Impressora remota: pasta dos pedidos", "texto"),
    ("impressora_remota_endereco", "Impressora remota: endereço de rede (IP:porta) ou nome da impressora do Windows", "texto"),
    ("balanca", "Balança", "escolha", [("Nenhuma", "Nenhuma"), ("Toledo", "Toledo"), ("Filizola", "Filizola")]),
    ("balanca_porta", "Porta da balança (ex.: COM1)", "texto"),
    ("gaveta", "Gaveta de dinheiro instalada", "sn"), ("leitor_optico", "Leitor óptico de código de barras", "sn"),
]

CAMPOS_CONFIG = [
    ("tema_visual", "Aparência do programa", "escolha", "Aparência",
     [("escuro", "Modo escuro (fundo escuro, o padrão)"), ("claro", "Modo claro (fundo claro)")]),
    ("caixa_tela_cheia", "Abrir o caixa em tela cheia (Ctrl+F alterna)", "sn", "Aparência"),
    ("mensagem_rodape", "Mensagem de rodape do cupom", "texto", "Impressao"),
    ("posicao_padrao", "Número digitado sem letra no caixa é", "escolha", "Mesas e serviço",
     [("comanda", "Comanda (a mesa é M + número, ex.: M5)"), ("mesa", "Mesa (a comanda é C + número, ex.: C2)")]),
    ("num_mesas", "Número de mesas / posições de consumo", "int", "Mesas e serviço"),
    ("num_comandas", "Número de comandas (0 = não usar comandas)", "int", "Mesas e serviço"),
    ("cobra_servico_mesa", "Cobrar serviço nas mesas", "sn", "Mesas e serviço"),
    ("cobra_servico_comanda", "Cobrar serviço nas comandas", "sn", "Mesas e serviço"),
    ("servico_pct", "Percentual de serviço (%)", "decimal", "Mesas e serviço"),
    ("controle_garcom", "Exigir o garçom ao fechar a mesa", "sn", "Mesas e serviço"),
    ("comissao_garcom_pct", "Comissão dos garçons sobre produtos (%)", "decimal", "Mesas e serviço"),
    ("tempo_inatividade_min", "Alertar mesa parada após (minutos, 0 = desligado)", "int", "Mesas e serviço"),
    ("pergunta_pessoas", "Perguntar o nº de pessoas ao abrir a mesa", "sn", "Mesas e serviço"),
    ("painel_mesas_fixo", "Mostrar sempre os ícones das mesas e comandas abertas no rodapé do caixa", "sn", "Mesas e serviço"),
    ("painel_mostra_garotas", "Mostrar no rodapé do caixa as garotas com comissão a pagar", "sn", "Mesas e serviço"),
    ("num_turnos", "Número de turnos por dia", "int", "Caixa"),
    ("usar_desconto", "Permitir desconto no fechamento da conta", "sn", "Caixa"),
    ("agrupar_itens_balcao", "Agrupar produtos iguais e da mesma temperatura no balcão", "sn", "Caixa"),
    ("virada_dia_hora", "O dia do painel e dos relatórios de vendas vira às (hora, 0 a 23; 6 = a madrugada conta na noite anterior)", "int", "Caixa"),
    ("margem_minima_pct", "Margem mínima para alertar após atualizar custo (0 = desligado)", "decimal", "Estoque"),
    ("exigir_senha_gaveta", "Exigir senha de supervisor para abrir a gaveta", "sn", "Caixa"),
    ("exigir_senha_sangria", "Exigir senha de supervisor para sangria", "sn", "Caixa"),
    ("exigir_senha_cancelamento", "Exigir senha de supervisor para cancelamentos", "sn", "Caixa"),
    ("exigir_motivo_cancelamento", "Exigir o motivo para cancelar item ou venda", "sn", "Caixa"),
    ("exigir_senha_desconto", "Exigir senha de supervisor para desconto", "sn", "Caixa"),
    ("exigir_senha_comissao", "Exigir senha de supervisor para lançar comissão das garotas", "sn", "Caixa"),
    ("codigo_comissao", "Código que lança a comissão das garotas no caixa (vazio = desligado)", "texto", "Caixa"),
    ("comissao_em_pontos", "Comissão das garotas em pontos (0,1, 0,2...) em vez de reais", "sn", "Caixa"),
    ("comissao_valor_ponto", "Quanto vale cada 0,1 ponto de comissão (R$)", "decimal", "Caixa"),
    ("comissao_paga_do_caixa", "Pagamento da comissão já vem marcado para sair da gaveta (sangria)", "sn", "Caixa"),
    ("imprimir_saida_ao_pagar", "Ao pagar a comanda ou mesa, imprimir junto o ticket de saída para a portaria", "sn", "Caixa"),
    ("codigo_saida", "Código que libera a saída da comanda sem consumo e imprime o comprovante (vazio = desligado)", "texto",
     "Caixa"),
    ("comissao_na_linha", "Marcar, pagar e cancelar a comissão das garotas na própria tela do caixa (desligado: abre janelas)", "sn", "Caixa"),
    ("imprimir_via_comissao", "Imprimir a via da garota a cada comissão lançada", "sn", "Caixa"),
    ("comissao_pede_shows", "Ao acertar a conta da garota, perguntar quantos shows ela fez (lançados pelo operador)", "sn", "Caixa"),
    ("show_valores", "Valores do show (R$), separados por ponto e vírgula. Ex.: 50;60", "texto", "Caixa"),
    ("imprimir_fechamento_ao_trocar", "Imprimir o fechamento ao trocar o turno (com a assinatura do caixa)", "sn", "Caixa"),
    ("vias_fechamento", "Vias do fechamento do turno (1 a 3)", "int", "Caixa"),
    ("consumacao_minima", "Consumação mínima por comanda (R$, 0 = desligada): na saída cobra a diferença até o mínimo", "int", "Mesas e serviço"),
    ("limite_comanda", "Limite de consumo da comanda do cliente (R$, 0 = sem limite): ao chegar nele não lança mais, tem que acertar a comanda", "int", "Mesas e serviço"),
    ("consumacao_minima_de", "Consumação mínima vale a partir da comanda nº (0 = todas)", "int", "Mesas e serviço"),
    ("consumacao_minima_ate", "Consumação mínima vale até a comanda nº (0 = sem limite; deixe de fora as comandas das garotas)", "int", "Mesas e serviço"),
    ("limite_gaveta", "Avisar para fazer sangria quando o dinheiro da gaveta passar de (R$, 0 = não avisar)", "int", "Caixa"),
    ("sangria_horarios", "Horários de sangria: lembra o caixa de fazer a sangria nestes horários (ex.: 02:00, 04:30; vazio = sem lembrete)", "texto", "Caixa"),
    ("imprimir_cupom", "Imprimir cupom ao fechar a venda", "sn", "Caixa"),
    ("usar_mesas", "Mesas e comandas no caixa (desligado: o caixa vende só no balcão, como numa adega ou loja)", "sn",
     "Módulos"),
    ("usar_garotas", "Garotas (casa noturna): comissão pelo código no caixa, shows, cadastro e relatório das garotas",
     "sn", "Módulos"),
    ("usar_portaria", "Portaria (casa noturna): ticket de saída junto com o cupom e código de saída da comanda sem consumo",
     "sn", "Módulos"),
    ("usar_delivery", "Delivery: pedidos de entrega (F6), bairros e taxas de entrega", "sn", "Módulos"),
    ("taxa_entrega_padrao", "Taxa de entrega padrão do delivery (R$)", "texto", "Módulos"),
    ("integracao_ifood_estado", "iFood (preparação apenas; não recebe pedidos)", "escolha", "Integrações",
     [("desativado", "Desativado"), ("preparacao", "Em preparação (sem operação)")]),
    ("integracao_nfce_estado", "NFC-e SP (preparação apenas; não emite notas)", "escolha", "Integrações",
     [("desativado", "Desativado"), ("preparacao", "Em preparação (sem operação)")]),
    ("nfce_regime_tributario", "Regime tributário para NFC-e (confirmar com o contador)", "escolha", "Integrações",
     [("nao_definido", "Ainda não definido"), ("simples_nacional", "Simples Nacional"),
      ("mei", "MEI (validar enquadramento com o contador)"), ("lucro_presumido", "Lucro Presumido"),
      ("lucro_real", "Lucro Real")]),
    ("usar_caderneta", "Caderneta: venda a prazo para clientes (F5) e cadastro de clientes", "sn", "Módulos"),
    ("usar_contas", "Contas a pagar/receber, plano de contas e relatórios financeiros", "sn", "Módulos"),
    ("usar_cozinha_bar", "Cozinha/Bar: imprimir por setor (impressoras nomeadas) e acompanhar o preparo dos itens "
     "(pendente/em preparo/entregue)", "sn", "Módulos"),
    ("usar_rodizio", "Rodízio: cobrança fixa por pessoa nas mesas/comandas marcadas (produtos do rodízio não "
     "entram na conta por item; cada mesa decide se é rodízio)", "sn", "Módulos"),
    ("valor_rodizio_pessoa", "Valor do rodízio por pessoa (R$)", "texto", "Módulos"),
    ("usar_prepago", "Pré-pago: o cliente carrega crédito na comanda (botão Recarga no caixa), só consome até o saldo e "
     "recebe a sobra de volta na saída", "sn", "Módulos"),
    ("programa_comunicacao", "Programa de comunicação (caminho do executável)", "texto", "Utilitários"),
    ("pasta_backup", "Pasta do backup (vazio = pasta Backup do sistema)", "texto", "Utilitários"),
    ("pasta_backup_extra", "Cópia extra do backup: pendrive, outro disco ou pasta de rede (vazio = sem cópia extra)", "texto", "Utilitários"),
    ("email_loja", "E-mail da loja", "texto", "E-mail"), ("email_destino", "E-mail de destino dos relatórios", "texto", "E-mail"),
    ("smtp_servidor", "Servidor de e-mail (provedor)", "texto", "E-mail"),
    ("chave_loja", "Chave da loja (licença)", "texto", "Nuvem"), ("api_url", "Endereço da nuvem (licença e atualizações)", "texto", "Nuvem"),
    ("api_token", "Token da API", "texto", "Nuvem"), ("sync_intervalo_seg", "Intervalo da verificação na nuvem (segundos)", "int", "Nuvem"),
    ("painel_dono", "Painel do dono no celular: enviar vendas fechadas, caixa e estoque para a nuvem", "sn", "Nuvem"),
    # Central do fornecedor (src/sync/ponte.py): usa o endereço da nuvem acima e um token só deste caixa.
    ("central_ponte_ativa", "Central do fornecedor: buscar a licença publicada e enviar o contato deste caixa", "sn", "Nuvem"),
    ("central_caixa_id", "ID deste caixa na central (passe ao fornecedor)", "texto", "Nuvem"),
    ("central_caixa_token", "Token do caixa emitido pelo fornecedor (não é o token da API)", "segredo", "Nuvem"),
    # O token do bot e o pareamento ficam na janela Configurações > Telegram (não aqui, para o token não aparecer em tela cheia).
    ("telegram_ativo", "Telegram ligado: avisar o celular do dono e responder aos botões (precisa parear em Configurações > Telegram)",
     "sn", "Telegram"),
    ("telegram_avisa_turno", "Avisar quando o caixa abrir e fechar (com a diferença do caixa)", "sn", "Telegram"),
    ("telegram_avisa_cancelamento", "Avisar cada venda/cupom cancelado (com o motivo e quem cancelou)", "sn", "Telegram"),
    ("telegram_avisa_item", "Avisar cada item cancelado (com o motivo e quem cancelou)", "sn", "Telegram"),
    ("telegram_avisa_sangria", "Avisar sangria e suprimento do caixa", "sn", "Telegram"),
    ("telegram_avisa_backup", "Avisar se o backup automático falhar", "sn", "Telegram"),
    ("telegram_avisa_estoque", "Avisar na hora quando um produto acabar ou chegar no ponto de pedido", "sn", "Telegram"),
    ("telegram_avisa_venda", "Avisar CADA venda fechada, em tempo real (em noite cheia são muitas mensagens)", "sn", "Telegram"),
    ("telegram_resumo_ativo", "Enviar resumo diário consolidado ao dono (pendente sai quando o PC voltar)", "sn", "Telegram"),
    ("telegram_resumo_hora", "Resumo diário neste horário LOCAL (padrão 23:00; vazio = não enviar)",
     "texto", "Telegram"),
]
_TIPO_CONFIG = {c[0]: c[2] for c in CAMPOS_CONFIG}
_OPCOES_CONFIG = {c[0]: [o[0] for o in c[4]] for c in CAMPOS_CONFIG if len(c) > 4}


# Módulos opcionais: o que cada chave "usar_*" desligada esconde dos menus (códigos de módulo de acesso).
#
# Convenção para módulos de operação por tipo de negócio: toda flag nasce em CONFIG_PADRAO como "usar_<modulo>" = "N";
# entra em CAMPOS_CONFIG na seção "Módulos" (acima), para aparecer em Configurações sem UI extra; se esconder item de
# menu, entra aqui. Se o módulo decide algo fora do menu (botão no caixa, aba no painel), o código daquele ponto chama
# banco.cfg_bool("usar_<modulo>", False) direto. Exceção: os recursos da casa noturna (usar_garotas, usar_portaria) e as
# mesas/comandas (usar_mesas) nascem "S", porque o sistema nasceu boate; quem os desliga é o perfil do estabelecimento.
MODULOS_OPCIONAIS = {
    "usar_mesas": {"rel_comandas", "rel_garcons"},
    "usar_contas": {"lanc_contas", "rel_financeiro", "cad_plano_contas", "cad_subplanos"},
    "usar_delivery": {"cad_bairros"},
    "usar_cozinha_bar": {"cad_setores_impressao", "util_cozinha"},
    "usar_garotas": {"cad_garotas", "caixa_comissao", "caixa_pagar_comissao", "rel_comissao_garotas"},
}

# Códigos especiais do caixa: (módulo que o usa, valor de fábrica, para que serve). Com o módulo desligado o código deixa de
# existir: não lança nada no caixa e fica livre para um produto.
CODIGOS_ESPECIAIS = {"codigo_comissao": ("usar_garotas", "50", "lançar a comissão das garotas"),
                     "codigo_saida": ("usar_portaria", "1002", "liberar a saída da comanda sem consumo")}


def codigo_especial(banco, chave: str) -> str:
    """O código especial em uso (`codigo_comissao` ou `codigo_saida`); vazio se foi apagado ou se o módulo dele está desligado."""
    modulo, padrao, _ = CODIGOS_ESPECIAIS[chave]
    if not banco.cfg_bool(modulo, True):
        return ""
    return (banco.cfg(chave, padrao) or "").strip()


def modulos_desligados(banco) -> set[str]:
    """Códigos de módulo escondidos porque a casa não usa o recurso (Configurações > Módulos)."""
    fora: set[str] = set()
    for chave, mods in MODULOS_OPCIONAIS.items():
        if not banco.cfg_bool(chave, CONFIG_PADRAO.get(chave) == "S"):
            fora |= mods
    if not banco.cfg_bool("usar_delivery", False) and not banco.cfg_bool("usar_caderneta", False):
        fora |= {"cad_clientes", "rel_clientes"}      # clientes só existem para a caderneta e o delivery
    return fora


class ConfigController:
    def __init__(self, banco):
        self.banco = banco
        aplicar_padrao_telegram_23h(banco)

    # --------------------------------------------------------------- loja
    def loja(self) -> dict:
        return dict(self.banco.um("SELECT * FROM loja WHERE id = 1"))

    def salvar_loja(self, dados: dict) -> None:
        validos = {c[0] for c in CAMPOS_LOJA}
        limpos = {k: (str(v).strip() if v is not None else None) for k, v in dados.items() if k in validos}
        if limpos.get("uf") and len(limpos["uf"]) != 2:
            raise ErroValidacao("UF deve ter 2 letras.", {"uf": "inválido"})
        if limpos.get("logotipo") and limpos["logotipo"] != self.loja().get("logotipo"):
            from src.core.identidade_visual import importar_logotipo
            limpos["logotipo"] = importar_logotipo(limpos["logotipo"], self.banco)
        self.banco.atualizar("loja", 1, limpos)

    def loja_cadastrada(self) -> bool:
        """A casa já informou o nome (o que sai no cabeçalho de todos os comprovantes)."""
        l = self.loja()
        return bool((l["nome_fantasia"] or "").strip() or (l["razao_social"] or "").strip())

    def cadastrar_loja(self, dados: dict) -> None:
        """Cadastro inicial da casa: o nome é obrigatório, o resto pode ser completado depois em Configurações > Loja."""
        if not (str(dados.get("nome_fantasia") or "").strip()):
            raise ErroValidacao("Informe o nome da casa: ele sai em todos os comprovantes.", {"nome_fantasia": "obrigatório"})
        self.salvar_loja(dados)
        self.banco.log("loja_cadastrada", str(dados.get("nome_fantasia")).strip())

    def nome_loja(self) -> str:
        l = self.loja()
        return l["nome_fantasia"] or l["razao_social"] or "PDV"

    # ------------------------------------------------------------- máquina
    def maquina(self, terminal: int | None = None) -> dict:
        terminal = terminal or self.banco.cfg_int("terminal", 1)
        r = self.banco.um("SELECT * FROM maquinas WHERE terminal = ?", (terminal,))
        if r is None:
            self.banco.inserir("maquinas", {"terminal": terminal})
            r = self.banco.um("SELECT * FROM maquinas WHERE terminal = ?", (terminal,))
        return dict(r)

    def salvar_maquina(self, dados: dict, terminal: int | None = None) -> None:
        atual = self.maquina(terminal)
        tipos = {c[0]: c[2] for c in CAMPOS_MAQUINA if c[0] != "terminal"}
        limpos = {}
        for k, v in dados.items():
            tipo = tipos.get(k)
            if tipo is None:
                continue
            if tipo == "sn":
                v = 1 if str(v).strip().upper() in ("S", "1", "SIM", "TRUE") or v is True else 0
            elif tipo == "int":
                try:
                    v = int(str(v).strip() or 0)
                except ValueError:
                    raise ErroValidacao(f"Valor inválido em '{k}'.", {k: "inválido"}) from None
                if k == "colunas_fita" and not 24 <= v <= 80:
                    raise ErroValidacao("A fita deve ter entre 24 e 80 colunas.", {k: "inválido"})
                if k == "impressora_termica_pino" and v not in (0, 1):
                    raise ErroValidacao("O pino da gaveta deve ser 0 ou 1.", {k: "inválido"})
            else:
                v = (str(v).strip() or None) if v is not None else None
            limpos[k] = v
        self.banco.atualizar("maquinas", atual["id"], limpos)

    # --------------------------------------------------------------- config
    _USO_CODIGO = {"codigo_comissao": "a comissão", "codigo_saida": "a saída"}

    def _formatar_codigo_especial(self, v: str, chave: str) -> str:
        """Até 13 letras ou números, sem espaços; 050 e 50 são o mesmo código."""
        v = v.strip()
        if not v:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9]{1,13}", v):
            uso = self._USO_CODIGO[chave]
            raise ErroValidacao(f"O código d{uso[0]} {uso[2:]} deve ter até 13 letras ou números, sem espaços.",
                                {chave: "inválido"})
        return str(int(v)) if v.isdigit() else v

    def _conferir_codigos_especiais(self, valores: dict) -> None:
        """Os códigos especiais em uso são reservados: não podem ser de um produto (que nunca seria vendido) nem iguais entre
        si. Conferido depois de gravar, com os módulos já no estado novo: ligar a comissão ou a portaria também confere o código
        dela. O código de um módulo desligado não disputa nada."""
        ativos = {}
        for chave in CODIGOS_ESPECIAIS:
            v = codigo_especial(self.banco, chave)
            if not v:
                continue
            achado = self.banco.um("SELECT nome FROM produtos WHERE codigo = ? OR cbarra = ? OR atalho = ? COLLATE NOCASE",
                                   (v.zfill(13) if v.isdigit() else v, v, v))
            if achado:
                raise ErroValidacao(f"O produto '{achado['nome']}' já usa o código {v}. Troque o código dele ou escolha "
                                    f"outro para {self._USO_CODIGO[chave]}.", {chave: "em uso"})
            ativos[chave] = str(int(v)) if v.isdigit() else v.lower()
        if len(ativos) == 2 and ativos["codigo_comissao"] == ativos["codigo_saida"]:
            campo = "codigo_saida" if "codigo_saida" in valores else "codigo_comissao"
            raise ErroValidacao("A comissão e a saída não podem usar o mesmo código.", {campo: "em uso"})

    @staticmethod
    def _validar_show_valores(v: str) -> str:
        """"50;60" -> "50;60". Valores em reais, separados por ponto e vírgula (a vírgula é dos centavos); no máximo 4."""
        partes = [p for p in re.split(r"[;/\s]+", v) if p]
        try:
            cents = [fmt.para_centavos(p) for p in partes]
        except ValueError:
            raise ErroValidacao("Valores do show inválidos. Use números separados por ponto e vírgula, ex.: 50;60.",
                                {"show_valores": "inválido"}) from None
        if not cents or any(c <= 0 for c in cents) or len(cents) > 4:
            raise ErroValidacao("Informe de 1 a 4 valores de show maiores que zero, ex.: 50;60.", {"show_valores": "inválido"})
        return ";".join(str(c // 100) if c % 100 == 0 else f"{c // 100},{c % 100:02d}" for c in cents)

    def todas(self) -> dict:
        return {c[0]: self.banco.cfg(c[0]) for c in CAMPOS_CONFIG}

    def salvar_config(self, valores: dict) -> None:
        from src.sync import ponte
        chaves_ponte = (ponte.CHAVE_ATIVA, ponte.CHAVE_CAIXA_ID, ponte.CHAVE_TOKEN, "api_url")
        ponte_antes = {c: self.banco.cfg(c) for c in chaves_ponte}
        with self.banco.transacao():
            for chave, valor in valores.items():
                if chave not in _TIPO_CONFIG:
                    raise ErroNegocio(f"Configuração desconhecida: {chave}")
                tipo = _TIPO_CONFIG[chave]
                v = str(valor).strip()
                if tipo == "sn":
                    v = "S" if v.upper() in ("S", "1", "SIM", "TRUE") else "N"
                elif tipo == "int":
                    try:
                        v = str(int(float(v.replace(",", ".") or 0)))
                    except ValueError:
                        raise ErroValidacao(f"Valor inteiro inválido em '{chave}'.", {chave: "inválido"}) from None
                    if int(v) < 0:
                        raise ErroValidacao(f"'{chave}' não pode ser negativo.", {chave: "inválido"})
                elif tipo == "escolha":
                    if v not in _OPCOES_CONFIG[chave]:
                        raise ErroValidacao(f"Escolha uma das opções de '{chave}'.", {chave: "inválido"})
                elif tipo == "decimal":
                    try:
                        v = str(float(v.replace(",", ".") or 0))
                    except ValueError:
                        raise ErroValidacao(f"Número inválido em '{chave}'.", {chave: "inválido"}) from None
                    if float(v) < 0 or float(v) > 100:
                        raise ErroValidacao(f"'{chave}' deve estar entre 0 e 100.", {chave: "inválido"})
                if chave in CODIGOS_ESPECIAIS:
                    v = self._formatar_codigo_especial(v, chave)
                if chave == "show_valores":
                    v = self._validar_show_valores(v)
                if chave == ponte.CHAVE_CAIXA_ID:
                    v = ponte.uuid_valido(v) or ""
                    if not v:
                        raise ErroValidacao("O ID do caixa na central precisa ser um UUID válido "
                                            "(ex.: 3f2b8c1e-0d4a-4e8f-9b6c-1a2b3c4d5e6f).", {chave: "inválido"})
                if chave == "telegram_resumo_hora":
                    try:
                        v = fmt.para_hora(v) or ""
                    except ValueError:
                        raise ErroValidacao("Horário do resumo inválido (use hh:mm, por exemplo 23:00).", {chave: "inválido"}) from None
                if chave == "num_mesas" and not 1 <= int(v) <= 999:
                    raise ErroValidacao("O número de mesas deve ficar entre 1 e 999.", {chave: "inválido"})
                if chave == "num_comandas" and not 0 <= int(v) <= 10000:
                    raise ErroValidacao("O número de comandas deve ficar entre 0 e 10000.", {chave: "inválido"})
                if chave == "virada_dia_hora" and not 0 <= int(v) <= 23:
                    raise ErroValidacao("A hora da virada do dia vai de 0 a 23.", {chave: "inválido"})
                if chave == "num_turnos" and not 1 <= int(v) <= 9:
                    raise ErroValidacao("O número de turnos deve ficar entre 1 e 9.", {chave: "inválido"})
                if chave == "vias_fechamento" and not 1 <= int(v) <= 3:
                    raise ErroValidacao("As vias do fechamento vão de 1 a 3.", {chave: "inválido"})
                if chave == "limite_gaveta" and int(v) > 1_000_000:
                    raise ErroValidacao("O limite da gaveta deve ficar abaixo de R$ 1.000.000.", {chave: "inválido"})
                self.banco.cfg_set(chave, v)
            if valores.keys() & (set(CODIGOS_ESPECIAIS) | {m for m, _, _ in CODIGOS_ESPECIAIS.values()}):
                self._conferir_codigos_especiais(valores)
            if ponte.ativa(self.banco) and any(self.banco.cfg(c) != ponte_antes[c] for c in chaves_ponte):
                ponte.validar_configuracao(self.banco)   # ligar ou mexer na central com dado faltando desfaz o salvamento
