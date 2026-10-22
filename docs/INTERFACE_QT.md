# Interface Qt

O Qt (PySide6) é a **única interface do PDV**; o código Tk do PDV foi removido (só o gerador de
licenças, `licenciador/`, segue em Tkinter). As menções ao "Tk" abaixo descrevem de onde veio cada
comportamento. Nunca mantenha dois programas abertos sobre o mesmo banco. Faça backup antes de homologar em uma cópia dos dados.

## Confiabilidade e operação na 1.9

- Visão geral com rolagem independente no menu e no conteúdo; `Ctrl+K` foca
  a busca de módulos, que continua ignorando acentos sem ampliar permissões.
- Verificação de backup por restauração isolada e situação do último ensaio
  no painel. Aprovação com avisos é diferente de comprovação sem alertas.
- Diagnóstico de impressora, gaveta, balança e leitor: abertura sem comandos
  físicos, confirmações com padrão Não e nova autorização após o diálogo.
  O diagnóstico foi testado com largura de 560 px e fonte aumentada.
- Conferência de fechamento por forma, declarações explícitas e justificativa
  obrigatória em divergências, compartilhando o controlador do Tk.
- Devoluções e trocas por cupom no menu e nas operações do caixa. Reembolsos
  têm relatório próprio pela data/turno do reembolso; vendas e CMV preservam
  o bruto histórico. Consulte as restrições em [devoluções](DEVOLUCOES.md).
- Fila com envio interrompido, conferência humana e reenvio autorizado,
  sem retry automático do estado incerto. Botões distribuídos em linhas.
- Telegram com agenda diária, recuperação de pendência e migração única
  autorizada para 23h; mudanças posteriores são respeitadas.

Roteiro e limitações: [melhorias 1.9](MELHORIAS_1_9.md). Estes ensaios não
certificam todos os detalhes ergonômicos nem equipamentos físicos.

## Início

Use Python 3.10+ e instale as dependências do projeto, incluindo
`PySide6-Essentials>=6.7,<7` (Qt Core/Gui/Widgets; não exige WebEngine).
```text
python -m src.app
```

Também existe uma entrada direta do piloto, com as mesmas proteções:

```text
python -m src.ui_qt.app
```

Se Qt não estiver instalado ou falhar, o início deve informar o erro e encerrar.
Não há fallback silencioso nem abertura de Tk dentro do processo Qt.
`--sync` continua sendo um modo separado do programa, não uma promessa de
sincronização contínua pelo painel Qt.

## O que já existe

- Login Qt com o `AcessoController` existente: senhas, tentativas/bloqueio e
  troca obrigatória da senha igual ao nome (inclusive ADM/ADM).
- Primeiro uso: após entrar, operador com `cfg_loja` recebe o convite para
  cadastrar a casa pelo `ConfigController.cadastrar_loja`. O nome é obrigatório
  para salvar; fechar adia o convite para a próxima entrada, como no Tk.
- Licença local pelas APIs existentes, preservando carência, relógio e isenção
  de turno recente. Ativação manual de código e consulta online em thread:
  só a rede sai da thread Qt; o banco e os widgets permanecem na thread principal.
  A consulta respeita a agenda/repetição existente, com tentativa forçada quando
  a licença está bloqueada. Falha de rede nunca concede autorização adicional.
- Menu principal com sessão, permissões, turno e estados reais de licença,
  último backup e consulta da nuvem. “Serviço iniciado” não significa impressão,
  mensagem entregue ou sincronização concluída.
- Produtos e operadores: listagem, pesquisa, inclusão, edição e exclusão.
  Campos/seções/lookups são derivados das entidades originais; conversões,
  centavos, validações, hashing e salvaguardas continuam no `CadastroController`.
  Edição de operador com senha vazia mantém a senha. Permissões são conferidas
  novamente antes de salvar/excluir, inclusive se o nível mudou com a tela aberta.
- Mais cadastros: unidades, grupos, subgrupos, observações, cargos, fornecedores,
  clientes, garotas, bairros, tipos de pagamento, plano/subplanos de contas e
  alíquotas usam o formulário genérico Qt e o `CadastroController`; a lista só
  oferece entidades habilitadas e autorizadas. Composição continua exigindo sua
  tela especializada Qt.
- Setores de impressão usam o mesmo cadastro genérico Qt: nome, conexão, pasta,
  endereço, ordem e ativo; o subgrupo permite vincular o setor. O recurso depende
  de `usar_cozinha_bar` e de `cad_setores_impressao`. Salvar um setor não imprime,
  instala driver ou confirma disponibilidade do destino.
- Cadastros oferecem pré-visualização/impressão textual e exportação CSV da
  pesquisa atual, sem incluir campos de senha. Produtos também oferecem tabela
  de preços e acesso às observações; clientes geram o arquivo de mala direta
  com os mesmos campos e separador do Tk, no destino escolhido explicitamente.
  Salvar/imprimir revalida a sessão e a permissão, inclusive após a confirmação.
- Cadastros também oferecem filtros pelos campos de relacionamento definidos nos
  metadados e “Somente ativos” quando aplicável, combinados à pesquisa textual.
  “Ordenar” alterna a ordem padrão da entidade e a ordem de cadastramento (`id`),
  preservando a seleção quando o registro continua visível. Visualização e CSV
  respeitam esses filtros e a ordem; cancelar o diálogo não altera a consulta.
  Aplicar filtros revalida o acesso após o diálogo. A mala direta continua
  exportando todos os clientes por nome, como no Tk.
- Composição/ficha técnica: busca de produto, consulta da composição e inclusão/
  exclusão de insumos pelas APIs de produto existentes, com acesso `cad_composicao`.
  Quantidades usam a unidade cadastrada do insumo; não há conversão nem alteração
  de estoque nesta tela.
- Estoque: busca por nome/código, situação e grupo, resumo e histórico pelas
  APIs existentes, com entrada, saída/descarte, contagem, mínimo e reposição.
  Movimentos e cadastros usam as permissões e regras existentes; não há
  movimentação automática apenas por consultar ou selecionar um produto.
- Relatório de vendas por período operacional: produtos de vendas fechadas e
  totalizações fornecidas pelo relatório existente, com valores em reais somente
  para exibição. Datas, virada do dia, autorização `rel_vendas` e consulta ficam
  no controlador; a janela é somente leitura.
- Contas a pagar/receber: cadastro, edição e cancelamento, filtros por datas,
  situação, previsão e busca, saldo/resumo, repetição mensal, quitação e reversão
  pelos métodos existentes de `ContasController`. O acesso `lanc_contas` é
  revalidado ao abrir e antes das operações; quitação só muda pelos botões próprios.
- Catálogo de outros relatórios: os 23 relatórios genéricos que já existiam no Tk
  usam `ctx.relatorios`, filtros equivalentes, as permissões de cada módulo e
  exportação CSV da estrutura comum, além de pré-visualização textual, salvar
  texto e envio explícito para impressão com confirmação e revalidação.
  A auditoria detalhada continua em sua tela
  própria; vendas por cupom e estoque atual usam telas Qt dedicadas.
- Configurações gerais: todos os campos de loja (inclusive slogan e caminho do
  logotipo), preferências, parâmetros/módulos e conexão com a nuvem em abas
  salvas separadamente pelo `ConfigController`. O token da API não é relido
  para exibição: vazio mantém o atual, substituição exige digitar um novo e
  remoção exige marcar a opção explícita. Tema claro/escuro vale também no Qt.
  Reabra as telas operacionais para reler parâmetros; configurar uma URL/token
  não inicia sincronização nem contrata nuvem. A aba da nuvem tem o botão
  "Trocar a senha do painel do dono…" (rede em outra thread, usa o endereço e o
  token já salvos; ver `docs/PAINEL_DONO.md`), que só troca essa senha.
- Máquinas e periféricos: configuração completa do terminal pelos campos do
  controlador, com testes explícitos de impressão/gaveta. Envio não comprova
  saída física; não instala drivers nem limpa filas do Windows.
- Níveis de acesso: edição dos níveis mínimos de cada módulo pela API de
  acesso existente, revalidando a sessão. Operadores continuam no cadastro próprio.
- Telegram: configuração, pareamento e diagnóstico em janela própria, com
  rede fora da thread dos widgets/banco e descarte de resultados após fechar.
  Testes dependem de credenciais reais; abrir a janela não comprova entrega.
- Atualizações: consulta manual e verificação periódica pelo mesmo serviço do
  Tk, em thread sem banco/widgets. O painel apenas avisa; download abre o link
  somente por ação explícita. Não instala automaticamente. Fechar a sessão
  descarta respostas tardias; falha não apaga o aviso previamente confirmado.
- Importação de produtos por CSV ou Excel: modelo/exportação, prévia com ações e
  linhas recusadas, opções de atualização/código e confirmação antes de gravar.
  Leitura, validação, centavos e transação pertencem a `ImportacaoProdutos`;
  cancelamento não grava. Exclusão em massa fica nos utilitários, com as
  confirmações e bloqueios existentes.
- Utilitários: backup local manual, pacote de suporte, limpeza do movimento,
  exclusão em massa de produtos e abertura do programa de comunicação. As
  ações destrutivas mantêm as confirmações do Tk e as validações do controlador;
  backup e suporte usam caminhos escolhidos/configurados, nunca enviam dados
  automaticamente a terceiros.
- Assistente de impressora: lista e sugere dispositivos do Windows, mostra
  diagnóstico, configura a selecionada e envia uma página de teste somente após
  autorização `cfg_maquinas`; confirma com a pessoa se o papel saiu. Não instala
  driver nem limpa/destrava filas. Enviar o teste sem erro não comprova impressão.
- Fila de impressão: consulta manual dos 300 registros mais recentes, reenvio,
  cancelamento e limpeza de enviados/cancelados com confirmação e acesso
  `util_fila_impressao`. Página de teste requer confirmação. A interface não
  processa a fila em background e status de envio não comprova saída física.
- Painel da Cozinha/Bar (`src.ui_qt.cozinha.JanelaCozinha(ctx, parent=None)`):
  acompanha a fila real de `PreparoController`, filtra por setor ativo, mostra
  posição, produto, quantidade, observação, minutos e situação. Iniciar preparo,
  marcar pronto e avançar usam os mesmos estados do Tk. Atualiza a cada dois
  segundos na thread principal; timer para ao ocultar/fechar. Cada consulta e
  alteração revalida operador ativo, `util_cozinha` e módulo habilitado;
  `exigir_acesso()` público também protege a reabertura pelo menu.
  Preparo não dispara impressão: pedidos continuam pelo fluxo de venda e a
  consulta/reenvio fica na Fila de impressão, sem duplicar pedidos no painel.
- Caixa aberto por `JanelaCaixa(ctx, parent)` em janela Qt não bloqueante,
  com referência conservada pelo menu. Seu escopo operacional é incremental;
  consulte os avisos da própria tela durante a homologação.
  Sem turno, exibe abertura pelo controlador (que valida licença). A troca de
  turno permanece nessa janela e volta à abertura. Fechamento é recusado durante
  gravações; balcão com itens pede confirmação para manter a venda aberta;
  mesa/comanda vazia é descartada ao sair. O turno nunca é fechado sozinho.
- Comissão das garotas no caixa Qt (`src/ui_qt/comissao.py`), pelos mesmos
  `ComissaoController`, `ImpressaoController` e `AcessoController` do Tk:
  código 50 na linha de entrada com `comissao_na_linha` ligada (Garota nº +
  valor/pontos, Enter avança, Esc descarta) ou pela janela com ela desligada.
  Mesmas senhas (`caixa_comissao`/`exigir_senha_comissao`, pagamento
  `caixa_pagar_comissao`/`exigir_senha_sangria`, cancelamento
  `caixa_cancelamento`/`exigir_senha_cancelamento`), mesmas perguntas (não
  cadastrada, inativa, valor alto) e a via da garota (`imprimir_via_comissao`).
  As comissões marcadas aparecem na comanda da garota; F12 ou "Pagar a garota"
  abre o acerto (shows, vale, Pix, se sai da gaveta) com recibo e, se houve
  sangria, comprovante de saída. Botão Comissões lista, lança, paga e cancela.
- Saída sem consumo (código 1002): libera a comanda/mesa vazia (ou pergunta qual),
  pelo `CaixaController.liberar_saida`, e emite o ticket de saída. Com consumo é
  recusada sem alterar a venda.
- **Operações do caixa** reúne os fluxos complementares, sem abrir Tk:
  - Adega/comércio sem mesas (`usar_mesas = N`): esconde painel e posição,
    desativa ações exclusivas de mesas e mantém delivery/caderneta conforme os módulos.
    Aceita `6*código`, cadastro rápido de código de barras desconhecido com permissão
    ou supervisor, escolha natural/gelada e quantidade de cascos sem troca.
    Atacado por temperatura, estoque compartilhado e agrupamento no balcão usam
    o mesmo controlador do Tk. Bebida e casco são itens independentes no cancelamento.
    O Cadastro de Produtos oferece a seção Adega e **Criar fardo**, sem criar
    estoque separado para o fardo. Regras e cuidados em [ESTOQUE.md](ESTOQUE.md).
  - Produto dividido/montagem: número de partes, escolha dos componentes e opção
    sem divisão; preço, elegibilidade, fracionamento e estoque pelo controlador.
    Desistir antes de lançar não cria uma venda vazia.
  - Desconto em centavos ou percentual (módulo `usar_desconto`, autorização
    `caixa_desconto`/`exigir_senha_desconto`), serviço manual, zero ou retorno ao
    automático em mesa/comanda. Recalcula os totais e mantém as regras de pagamento.
  - Observação do item: cadastro ou texto livre quando não há opções, somente em
    produto habilitado; reenvia o item à impressora remota.
  - Transferência total, várias origens e quantidade parcial de item, entre mesas
    e comandas na notação da loja. Mesclagem, pagamentos e arredondamento continuam
    nas APIs existentes; comissão não é transferida como se fosse consumo.
  - Pré-conta (F8), sem encerrar a venda; em entrega, F8 emite o pedido.
    Falha de impressão mantém o estado gravado e mostra o documento quando possível.
  - Caderneta (F5, módulo `usar_caderneta`): pesquisa/confirmação/inclusão de cliente,
    venda a prazo com confirmação e limite, recebimento sem itens, escolha entre
    crédito e troco para excedente, consulta de devedores, últimas compras, extrato
    e detalhes dos débitos/créditos. Não se recebe pagamento em venda a prazo com
    itens. Inclusão reutiliza o formulário Qt e as permissões do cadastro existente.
  - Entrega (F6, módulo `usar_delivery`): cliente, taxa por bairro/padrão, troco,
    mensagem, entregador opcional, emissão, pendentes com tempo/endereço, atribuição
    de entregador/saída, retomada para receber e cancelamento autorizado.
    Troca de modalidade não abandona itens nem pagamentos da venda atual.
  - Sangria/suprimento com autorização `caixa_sangria`/`exigir_senha_sangria`,
    comprovante e solicitação da gaveta; repique associado à posição pelo
    `TurnoController`. Movimento gravado não é repetido quando a impressão falha.
  - Gaveta manual com autorização `caixa_gaveta`/`exigir_senha_gaveta` e registro
    da tentativa; indisponibilidade não é anunciada como abertura bem-sucedida.
    Captura de peso pela API da balança ou peso manual explícito quando indisponível,
    sem lançamento automático; quantidade continua validada pelo controlador.
  - Reimpressão de último cupom ou por número, fechado/cancelado, como segunda via,
    sem novo pagamento nem abertura de gaveta.
  - Consulta de comanda sem trocar a venda da tela: paga, aberta/conta enviada,
    vazia, cancelada ou sem registro, incluindo comissão pendente da garota.
    O modo de cancelamento permite selecionar linhas com Enter após autorização
    única para a venda/operador atual; Esc ou troca de posição descarta a autorização.
    Comissão paga continua não cancelável, e comissão nunca vira item de consumo.
- Encerrar sessão fecha as janelas e volta ao login; um caixa que recusa fechamento
  impede o logout. Encerrar sessão ou programa não fecha o turno automaticamente.
- Auditoria administrativa, somente leitura: acessível pelo menu para administrador
  ativo de nível 4 com `rel_auditoria`. Usa exclusivamente `ctx.auditoria.listar`,
  com filtros de início/fim ISO local inclusivos e ação (seleção ou código exato),
  páginas de 100 eventos e retratos JSON antes/depois. Os valores monetários dos
  retratos permanecem em centavos; senhas são omitidas pelo mecanismo de auditoria.
  Não há edição, exclusão nem consulta ao backend. Página cheia pode ter sucessora;
  não se inventa um total. A autorização é revalidada no controlador ao consultar,
  reabrir a tela e selecionar detalhes; acesso negado limpa os dados exibidos.
  Não é um monitor em tempo real: reaplique filtros/reabra para atualizar.
- Backup externo cifrado (permissão `util_backup`): configuração, exportação manual,
  verificação com senha, preparação de restauração e desativação, pelos métodos
  existentes do `UtilitarioController`. Senha de recuperação tem mínimo de 12
  caracteres e deve ser digitada duas vezes na configuração/exportação.
  A interface não grava senha em QSettings ou no banco. Guarde-a fora do PC.
  Configuração automática depende de DPAPI no Windows; exportação manual solicita
  a senha na hora e exige uma pasta previamente configurada no controlador.
  A cópia cifrada não prova upload para a nuvem. Restauração exige digitar
  `RESTAURAR`, é apenas preparada e acontece no próximo início protegido.
- Restauração local (permissão `util_backup`): consulta até 60 backups válidos,
  permite selecionar um e, após confirmação das consequências, marca a restauração
  pela API protegida existente. O banco aberto não é substituído; a operação só se
  conclui no próximo início.

## Proteções e ciclo de vida

`preparar_inicio()` consome `InstanciaUnica`, `protecao.preparar_banco` e
`registro.configurar_logs`, as mesmas APIs do bootstrap atual, usando apenas
perguntas Qt. A trava é mantida até a saída. Cancelamento, falha de integridade
ou erro de início não permitem continuar sem proteção.

Com banco em arquivo, o ciclo executa backup inicial quando ausente/antigo
(12 horas), backup de saída com intervalo mínimo de 60 minutos e inicia/para os
serviços já existentes de impressão e Telegram. Falhas ficam no log e no estado
do painel; não são exibidas como sucesso. A instância padrão do banco é fechada
ao sair.

`App(banco=..., aplicacao=...)` aceita banco em memória e `QApplication` existente
para testes/integração. Um banco injetado pertence ao chamador e não é fechado
pelo aplicativo. Bancos em memória não iniciam serviços de arquivo nem backups.
O construtor `App` não substitui o bootstrap protegido: produção usa `main()`.
Quando já há `QApplication`, `main()` não chama `exec()` novamente e conserva o
aplicativo e a trava até `aboutToQuit`; o hospedeiro é responsável pelo loop.

Temporizadores são parados ao fechar as janelas. A consulta online recebe um
sinal de cancelamento e descarta resultados tardios sem acessar banco/widgets.
Uma requisição HTTP já em curso não pode ser interrompida pelo binding Qt:
ela termina sob os timeouts de conexão/leitura (3/5 segundos), em thread daemon,
sem segurar o processo. Não se usa `terminate()` inseguro.

## Limites assumidos

A cobertura é descrita acima; isso não certifica paridade de todos os detalhes
ergonômicos nem a homologação operacional. Não há mais interface alternativa.

Os fluxos de caixa listados acima estão disponíveis no piloto; isso não substitui
homologação em cópia do banco. Impressão, gaveta e balança precisam de homologação
com os periféricos reais. Cancelar a entrada manual de peso não simula uma leitura;
sem configuração/driver/dispositivo, a interface informa a limitação.

Não há sincronização contínua de vendas pelo painel Qt. Não abra duas instâncias sobre o mesmo banco. Status de backup/licença
não substitui os testes de recuperação e de periféricos reais.

## Testes

Os testes importam Qt de verdade; pacote ausente é erro de dependência, não
motivo para pular silenciosamente:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -p "test_qt_*.py"
```

Há cobertura de autenticação, troca obrigatória, bloqueio por licença,
isenção de turno, consulta não bloqueante/cancelamento, formulários, centavos,
permissões, sessões, integração de janela de caixa, proteções iniciais e ciclo
de backup/serviços. Banco de teste é em memória e não usa a loja.
Comissão e saída cobrem os modos na linha/janela, conversão pontos/reais,
autorizações de supervisor, confirmações de cadastro/valor, acerto com shows,
vale e Pix, cancelamento, F12 e preservação dos registros quando a impressão falha.
`test_qt_caixa_operacoes` cobre montagem, desconto/serviço, observações,
transferências, pré-conta, caderneta (débito/crédito/troco/limite/consulta),
entrega completa, movimentos financeiros, autorizações, cancelamento de entradas,
gaveta indisponível, captura/manual de peso, segunda via, consulta com comissão,
modo cancelar e recusa das operações sem turno/durante gravação.
`test_qt_contas` cobre os fluxos financeiros e `test_qt_app` cobre a integração
da janela ao menu, janela única e revalidação do acesso.
`test_qt_cozinha` cobre filtro por setor, transições, auditoria de operador,
seleção obsoleta, cancelamento, revogação e encerramento do timer.
`test_qt_cadastros_extras` cobre setores/vínculo de subgrupo, CSV filtrado,
tabela sem envio automático, mala direta, cancelamento e revalidação após
diálogos de destino/exclusão. Todos usam banco em memória e saídas simuladas.
Configurações completas cobrem máscaras de token, preservação de campos não
alterados, rollback de parâmetros inválidos e aparência clara/escura.
Homologue também teclado, escala de tela, leitores, impressoras e os fluxos
operacionais efetivamente disponíveis no caixa.

Para integração com `--autoteste`, `src.ui_qt.app.autoteste(pasta: Path) -> list[str]`
reaproveita `QApplication` quando existente, abre menu e os dois cadastros reais,
confere comissão na linha, painel, diálogos de comissão/acerto e saída sem consumo,
fecha tudo e processa destruições pendentes. O turno é um cenário inserido somente
no banco em memória: não ativa licença nem modifica a exigência de produção.
O banco efêmero é em memória; a pasta
é aceita pelo protocolo do autoteste, mas não recebe arquivos. Não inicia rede,
periféricos, serviços nem o bootstrap sobre o banco de loja. Falhas levantam exceção;
sucesso devolve mensagens para o relatório do chamador.

## Distribuição e licenças

PySide6/Qt for Python oferece licenciamento LGPLv3/GPLv3 e comercial, com termos
específicos dos componentes distribuídos. O piloto usa Core/Gui/Widgets.
Antes de distribuir instaladores, confira os textos e avisos de licença das
versões efetivamente incluídas, componentes de terceiros e obrigações aplicáveis
ao método de empacotamento/redistribuição. Esta documentação não é parecer jurídico
nem afirma que uma forma de distribuição está automaticamente em conformidade.

Referências oficiais:
- https://doc.qt.io/qtforpython-6/licenses.html
- https://doc.qt.io/qt-6/licensing.html
