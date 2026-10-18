# HANDOFF

## Último trabalho

Continuação do módulo **Adega / depósito de bebidas**, sobre os commits `7cd4090` e `2f28d41`.
O titular confirmou as prioridades e regras por formulário. Três agentes trabalharam em arquivos
separados (caixa Tk, caixa Qt e cadastro); o titular da sessão integrou regras, migração e testes.

### Entregue

- **Cadastro > Produtos > Adega** (descrição compartilhada entre Tk e Qt):
  preço gelada opcional, mínimo/preço unitário de atacado natural, mínimo/preço unitário de
  atacado gelada e produto de casco vinculado. Validações consideram alterações parciais.
- **Natural e gelada** compartilham produto/estoque. Produto com preço gelado pergunta a
  temperatura antes de lançar. A temperatura fica no item e a observação preserva "Gelada"
  para impressão, inclusive depois de editar observações.
- **Atacado automático somente no balcão**, por produto e temperatura. Ao atingir o mínimo,
  reprecifica todas as linhas elegíveis da venda; cancelar abaixo do mínimo restaura a base.
  O preço-base é preservado em cada leitura; montagens e itens antigos sem base não são
  reprecificados. Natural compara promoção vigente com atacado; gelada compara seu próprio
  varejo com seu próprio atacado.
- **Cascos simples**, sem empréstimo ou saldo: cadastrar CASCO como produto e vinculá-lo à
  bebida; ao vender, informar quantos cobrar (0 = todas as trocas). Bebida e casco são
  lançados numa transação, mas são produtos independentes no cancelamento. Os diálogos avisam
  que cancelar a bebida não cancela o casco. Não há entrada automática das trocas.
  Vínculo somente em bebida por unidade, sem composição/fardo/montagem/fracionamento.
  Também bloqueia criar composição/fardo depois do vínculo. Desativar ou excluir casco
  referenciado orienta desvincular nas bebidas primeiro.
- **Agrupar leituras repetidas**: configuração `agrupar_itens_balcao` em Configurações > Caixa;
  perfil Adega liga, demais perfis mantêm desligado. Separa temperatura, observação,
  operador, preço-base e montagem; respeita limite por linha. Não agrupa itens preparados nem
  categorias com impressão remota, para não reenviar quantidades acumuladas à cozinha/bar.
  Delete cancela toda a linha agrupada.
- **Tk**: faixa de orientação de balcão, atalhos visíveis de pagamento/delivery/caderneta,
  resumo de quantidades natural/gelada, economia no atacado e indicação das faixas.
  Novo `src/ui/adega_dialogos.py` registrado também em `src/autoteste.py`.
- **Qt**: adega sem painel/posição/ações de mesa, `6*código`, cadastro rápido de EAN
  desconhecido com permissão/supervisor, temperatura e cascos. Cadastro ganhou **Criar fardo**
  usando o controlador existente. Delivery/caderneta preservados. Continua opt-in.
- **Esquema v22**: colunas comerciais em produtos; temperatura e preço-base em itens_venda.
  Atualiza gatilhos de auditoria para registrar os novos campos. Migração liga agrupamento
  para adega já existente sem sobrescrever configuração explícita; backup prévio permanece
  no mecanismo padrão. Teste confirma integridade, FKs e preservação dos preços antigos.
- Guia atualizado em `docs/ESTOQUE.md`; paridade de adega em `docs/INTERFACE_QT.md`; mapa atualizado.
  Nenhum banco real foi migrado nem instalador foi gerado nesta sessão.

### Validação

- Novos testes: `test_adega_regras.py`, `test_adega_cadastro.py`, `test_adega_tk.py`,
  `test_adega_qt.py` (102 casos ao todo). Ajustada a expectativa antiga de leituras repetidas
  em `test_adega.py` para a regra de agrupamento confirmada pelo titular.
- Suíte completa: `QT_QPA_PLATFORM=offscreen`, `python -m unittest discover -s tests`:
  **2070 testes, 62 ignorados, uma falha** (faltava registrar o novo diálogo em MODULOS).
  Essa falha foi corrigida em `src/autoteste.py`.
- Após a correção: **192 testes passaram** em uma execução conjunta de
  `tests.test_autoteste`, `tests.test_adega`, `tests.test_adega_regras`,
  `tests.test_adega_cadastro`, `tests.test_adega_tk`, `tests.test_adega_qt`,
  `tests.test_qt_caixa`, `tests.test_qt_caixa_operacoes`, `tests.test_qt_composicao`.
  A suíte completa não foi repetida após a correção pontual do registro.
- Também passaram seletores de migrações antigas, pré-pago, cozinha, estoque, histórico,
  auditoria, importação e perfis. Pylance sem diagnósticos de erro nas telas/controladores
  alterados; `git diff --check` limpo.

## Pendências

- **Homologar antes de instalar:** leitor, impressora, gaveta e balança reais; testar natural/
  gelada, limiar do atacado, cancelamento das duas linhas de bebida/casco e estoque de fardos
  em cópia do banco. Não houve validação com periféricos físicos.
- **Promoção por temperatura:** foi mantida a promoção antiga somente no preço natural,
  e isso está explícito no guia. A tentativa de confirmar esse detalhe ao final não recebeu
  resposta (titular indisponível). Se ele quiser promoção também na gelada, confirmar a regra
  e ajustar controlador/prévias/testes juntos; não usar preço natural como substituto do gelado.
- **NFC-e:** ainda não emite documento fiscal, somente cupom NÃO FISCAL. Conferir exigências
  da SEFAZ antes de instalar em adega/comércio. Exige certificado/integração; não foi feito.
- Retornáveis avançados (empréstimo, depósito/reembolso, saldo por cliente), etiquetas de
  gôndola e múltiplas faixas de atacado ficaram fora desta etapa.
- **Qt fora da adega:** ainda alinhar com Tk os demais recursos pendentes (pré-pago,
  rodízio/perfil na operação, impressão por setor, dividir conta, balança automática,
  corte/acerto de garotas e tipografia dos comprovantes). Esta entrega não certifica
  paridade integral do Qt. Não abrir Tk e Qt simultaneamente sobre o mesmo banco.
- **Pré-pago:** confirmar com titular a devolução em dinheiro de saldo recarregado por crédito
  (risco de "saque"); evoluções: comprovante de recarga, RFID e relatório de recargas.
- Demais evoluções preservadas: split por item, rodízio por faixa, EAN de balança,
  consumação mínima por entrada e cobrança de comanda sem consumo (ESPECIFICACAO seção 3).
- Homologar backup/restauração em outra máquina; configurar pasta do Google Drive e senha
  do cofre do licenciador; conferir cartões 184x126/faixa 52 e impressão física.
- Regra de renovação a partir do vencimento atual ainda pede autorização do titular.
- Asaas/nuvem: homologar credenciais/webhook e hospedar API/worker supervisionados antes
  de contratar. Painel web e múltiplos caixas continuam fora de escopo.
