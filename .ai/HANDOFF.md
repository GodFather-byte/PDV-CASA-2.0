# HANDOFF

## Último trabalho
- **Módulos de operação configuráveis** (Configurações > Módulos): formalizada a convenção de
  reaproveitar `CONFIG_PADRAO`/`CAMPOS_CONFIG`/`MODULOS_OPCIONAIS`/`modulos_desligados()`
  (`src/controllers/config_controller.py`, comentário acima de `MODULOS_OPCIONAIS`; detalhe em
  `docs/ESPECIFICACAO.md`, seção 2) para transformar o PDV, hoje só de casa noturna, num
  ecossistema que também sirva bar/restaurante/churrascaria/pequeno comércio — sem tocar na
  comissão de garota/shows, que fica como está.
- Primeiro módulo entregue ponta a ponta: **Cozinha/Bar** (`usar_cozinha_bar`, esquema v19):
  - Tabela `setores_impressao` (impressoras remotas **nomeadas**, não mais uma só por terminal).
    `subgrupos.setor_impressao_id` escolhe o setor (opcional; `impressora_remota` continua
    decidindo o que vai para a cozinha, sem mudança). `fila_impressao.setor_id` guarda o
    roteamento. Sem setor cadastrado em nenhum subgrupo, nada muda para quem já usa (boate).
  - `itens_venda.status_preparo` (pendente|em_preparo|entregue) + `preparo_atualizado_em` /
    `preparo_operador_id`. Controller `src/controllers/preparo_controller.py`
    (`PreparoController.fila/marcar/avancar`). Tela `src/ui/cozinha_ui.py`
    (Utilitários > Painel da Cozinha/Bar, módulo `util_cozinha`).
  - Cadastro de setores via CRUD declarativo (`entidades.py`, sem tela nova) — Cadastros >
    Setores de Impressão, módulo `cad_setores_impressao`.
  - `ImpressaoController.enviar_remoto` ganhou parâmetro opcional `setor`; `pedido_remoto` não
    mudou de assinatura. `FilaImpressao.enfileirar` ganhou `setor_id` opcional; `_enviar_padrao`
    virou método (`_enviar_padrao_setor`), com acesso ao banco para resolver a conexão do setor.
  - Observação por item (tecla O no caixa) já existia e já aparece no ticket remoto — nenhuma
    mudança, só confirmado que o módulo de cozinha reaproveita.
  - **Qt (`src/ui_qt/caixa.py`) NÃO recebeu o roteamento por setor** — continua indo para a única
    impressora remota da máquina mesmo com setor cadastrado. Ver Pendências.
- Testes a escrever/confirmar (próxima rodada, se ainda não houver): migração v18→v19 preserva
  dados; `usar_cozinha_bar` nasce desligado e esconde `cad_setores_impressao`/`util_cozinha`;
  `PreparoController` (fila filtra por subgrupo remoto/setor/cancelado, `marcar`/`avancar`
  validam e gravam quem/quando); impressão remota usa a conexão do setor quando há um cadastrado
  e mantém o comportamento atual quando não há.

## Pendências
- **Qt do módulo Cozinha/Bar**: alinhar `src/ui_qt/caixa.py` com o Tk (roteamento de impressão
  por setor). Mesma observação já valia para o acerto da garota no Qt (ver linha abaixo).
- **Próximos módulos de operação** (mesma convenção documentada em `config_controller.py` e
  `docs/ESPECIFICACAO.md`, cada um como fatia independente, não implementados ainda):
  - **Rodízio por pessoa**: cobrança fixa por pessoa no fechamento da conta (não em
    `itens_venda`); `usar_rodizio` + valor configurável; decidir como interage com
    desconto/serviço em `CaixaController.fechar`.
  - **Venda por peso**: `produtos.balanca` já existe; falta o fluxo de pesagem no caixa ligado à
    balança (`src/hardware/dispositivos.py`) atrás de `usar_venda_peso`.
  - **Split de conta**: dividir pagamento de uma mesa/comanda entre N formas/pessoas antes de
    fechar; `pagamentos_venda` já aceita múltiplos registros por venda — decidir o desenho da
    tela com o titular antes de tocar em esquema.
- Qt (`src/ui_qt/`, opt-in) ainda tem a regra antiga do acerto da garota (`_acerto_so_de_shows`,
  `comissao.py`) e o recibo/comprovante com o tipo antigo (letra normal); o texto do recibo já
  vem sem os lançamentos. Alinhar com o Tk se o Qt for substituir o Tk. O painel Qt do
  balcão/comandas também não foi redimensionado.
- Titular: conferir na prática o tamanho dos cartões (184x126) e da faixa (`ALTURA_FAIXA = 52`),
  e a letra do recibo na impressora real; ajustar as constantes se precisar.
- Titular: instalar o Google Drive para computador, escolher a pasta na aba Backup do WillPDV
  Licenças e anotar a senha da chave.
- Ideia aberta (pede OK do titular, regra de licença): renovar a partir do vencimento atual para
  o cliente não perder dias.
- Homologar em cópia do banco, com periféricos reais: comissão/acerto/saída, gaveta,
  teclado/escala. Backup do PDV: escolher pasta e senha no caixa e ensaiar recuperação em outra
  máquina.
- Asaas (quando houver nuvem): homologar sandbox/credenciais/webhook e hospedar API e
  `python -m backend.worker_asaas` sob supervisão; validar custos antes de contratar.
- Painel web e múltiplos caixas seguem fora de escopo.
