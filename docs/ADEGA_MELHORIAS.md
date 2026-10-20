# Adega: diagnóstico e plano de melhorias

## Resumo executivo

Esta entrega incremental melhora a conferência de preços no caixa Tk e Qt, agiliza a escolha de cascos no Tk
e acrescenta uma **Visão Adega** aos dois painéis de estoque. Não muda valores cobrados, promoções, baixa de estoque,
fardos, permissões ou esquema do banco. O fluxo de venda continua exclusivamente no `CaixaController`.

Referências: [implantação da Adega](ADEGA.md), [regras e movimentos de estoque](ESTOQUE.md) e
[importação de produtos](IMPORTAR_PRODUTOS.md).

## Diagnóstico do estado atual

- Natural e gelada compartilham estoque. A temperatura é escolhida quando há preço gelada cadastrado.
- Atacado é automático **somente no balcão**; soma a quantidade da mesma bebida e temperatura, inclusive entre linhas
  não agrupadas. Natural e gelada têm faixas próprias. Uma promoção natural mais barata não é substituída pelo atacado.
- Leituras repetidas podem agrupar itens; cancelar uma linha abaixo do mínimo recalcula o atacado.
- Casco vinculado é cobrado como outro item, na mesma transação de lançamento. Troca completa significa cobrar zero.
  O limite continua sendo a parte inteira da quantidade de bebidas; não há empréstimo/saldo por cliente.
- Fardos baixam unidades pela composição; não possuem um segundo estoque independente.
- O estoque já tem filtros, mínimo, histórico, perdas, contagem e sugestão de compra até o dobro do mínimo.
- Antes desta entrega, havia etiquetas de temperatura/atacado, mas sem explicação compartilhada da faixa aplicada;
  no Tk, informações na observação podiam ficar ocultas em telas estreitas.
- O Qt é uma interface em migração. O atalho e a prévia de cascos desta entrega são específicos do diálogo Tk;
  o fluxo Qt de cascos existente permanece intacto.

## Problemas operacionais mais prováveis

1. Operador não consegue explicar por que seis unidades naturais atingem atacado, mas três naturais e três geladas não.
2. Digitação repetitiva de zero ou do máximo de cascos e surpresa com o acréscimo no fechamento.
3. Cancelar a bebida e esquecer o casco, pois são linhas independentes.
4. Comprador mistura conveniência e bebidas com o restante da loja ou não identifica rapidamente rupturas.
5. Cadastro sem mínimo/controle de estoque impede uma boa sugestão de reposição.
6. Comprar pelo dobro do mínimo ignora giro, prazo do fornecedor e picos de sexta/sábado.

São hipóteses operacionais, não incidentes medidos. Devem ser confirmadas na loja com as métricas abaixo.

## Melhorias priorizadas e critérios de aceite

| Item | Prioridade | Entrega | Critério de aceite |
|---|---|---|---|
| Explicação do preço | Alta | Implementada, Tk/Qt | Exibir modalidade quando há escolha de temperatura; atacado aplicado mostra mínimo da mesma bebida/temperatura e economia por linha. Selecionar a linha no Tk mostra detalhes mesmo em notebook; Qt também oferece dica ao passar o mouse. |
| Compatibilidade de preços | Alta | Implementada | Entrega/caderneta não exibem economia como atacado; item antigo sem preço-base não inventa economia; cancelamento e agrupamento mantêm os cálculos existentes. |
| Cascos rápidos | Alta | Implementada, Tk | Botões e F2 “Todas trocas” / F3 “Sem troca” preenchem sem confirmar; Enter confirma e Esc cancela. Prévia muda imediatamente com a quantidade. |
| Validação de cascos | Alta | Implementada, Tk | Recusar vazio, negativo, fração, texto e valor acima do limite sem fechar o diálogo; permitir corrigir. Quantidade fracionada de bebida explica o limite arredondado para baixo. |
| Recorte operacional | Alta | Implementada, Tk/Qt | Estoque > Visão > Adega combina Sem estoque/Repor, grupo e busca; destaca categoria e prioridade; voltar a Geral restaura o recorte anterior do estoque geral. |
| Reposição visível | Alta | Implementada | Ruptura = Alta, ponto de pedido = Média, normal = Baixa; sem controle = Definir controle. Sem mínimo continua sem quantidade sugerida, mesmo em ruptura. |
| Reposição por giro e prazo | Média | Próxima recomendada | Comparar sugestão com consumo diário e prazo, explicar cálculo e exigir revisão antes de gerar pedido. Ver Top 1. |
| Paridade de cascos no Qt | Média | Planejada | Prévia e atalhos equivalentes ao Tk, preservando cancelamento e lançamento transacional; testes de interface Qt. |
| Cancelamento parcial guiado | Média | Planejada | Alterar quantidade recalcula atacado e permite conferir casco sem apagar histórico; exige decisão de produto sobre vínculo bebida/casco. |
| Importação de atacado gelada e etiquetas | Média | Planejada | Prévia da planilha valida faixa/preço; etiqueta distingue temperaturas e unidade/fardo, com testes de importação. |
| Saldo de cascos por cliente | Baixa | Planejada | Somente após definir empréstimo, caução, devolução e auditoria com o dono; nunca inferir dívida de trocas antigas. |
| Combos e múltiplas faixas | Baixa | Planejada | Definir precedência com promoções antes de implementar; testar margem, composição e estoque sem dupla baixa. |

## Como usar esta versão

### Caixa

1. Lance a bebida, escolha natural/gelada quando solicitado e alcance o mínimo de atacado.
2. Confira a etiqueta e a explicação: por exemplo, “Atacado gelada: a partir de 6 un da mesma bebida/temperatura;
   economia nesta linha: R$ 6,00”.
3. No Tk, a área abaixo da grade mostra o último item ou a linha selecionada; a observação também traz a explicação.
   O resumo mantém a economia total do atacado. No Qt, a descrição da linha e a dica das células trazem os detalhes.
4. A economia compara o total da linha com o preço-base unitário registrado multiplicado pela quantidade, em centavos.
   Não inclui desconto global, taxa de entrega nem soma natural e gelada para atingir a faixa.

### Cascos (Tk)

1. Use **Todas trocas (F2)** para cobrar zero ou **Sem troca (F3)** para cobrar o máximo.
2. Para troca parcial, digite apenas quantos cascos faltam. Confira “Impacto dos cascos: + R$ …”.
   A prévia considera promoção e atacado dos cascos, inclusive a reprecificação dos cascos naturais anteriores
   da mesma venda. Pode mostrar redução (sinal negativo) ao atingir uma faixa. Não inclui taxas/desconto global.
3. Confirme com Enter. Entrada inválida deixa o impacto indisponível e pede um inteiro entre zero e o máximo.
4. Em desistência, confira **as duas linhas**: cancelar bebida não cancela casco, nem o contrário.

### Estoque

1. Abra Estoque e selecione **Visão: Adega**; os cartões/resumo contam somente esse recorte, sem depender do filtro de situação.
2. Use **Sem estoque** para rupturas e **Repor** para saldo positivo até o mínimo, inclusive o limite exato.
3. Combine grupo e busca. Priorize Alta, depois Média. A lista Adega começa pelas rupturas e depois pelo ponto de pedido.
4. Confira categoria, saldo, mínimo e reposição sugerida; ajuste o cadastro quando faltar mínimo/controle.
5. **Gerar pedido do que falta e Lista de compras continuam gerais**, independentemente da visão, como antes.
   Revise o conteúdo antes de comprar; esta versão não gera automaticamente um pedido exclusivo da Adega.

## Decisões conservadoras e limites técnicos

- Sem categoria obrigatória ou migração. O recorte reconhece grupos Adega/Bebidas/Conveniência, subgrupos típicos
  (Cervejas, Destilados, Vinhos e espumantes, Refrigerantes, Águas e sucos, Energéticos, Gelo e carvão), ignorando
  caixa e acentos; também inclui produtos com preço gelada, faixa de atacado ou vínculo de casco e os cascos vinculados.
  Não tenta classificar pelo nome do produto. Atacado pode incluir itens de outras áreas: é um recorte operacional
  indicativo, não uma classificação fiscal. Cadastros personalizados sem esses sinais podem ficar fora: use Geral.
- O painel usa os joins já existentes e uma subconsulta de conjunto para identificar cascos, não uma consulta por produto.
  Os filtros existentes continuam combináveis. Não há previsão de cobertura em dias nesta versão.
  Consulta mais resumo de 5.000 produtos sintéticos em SQLite em memória levou aproximadamente 53 ms no ambiente Linux
  de desenvolvimento; não inclui renderização das grades nem representa garantia no hardware da loja.
- A explicação compartilhada está em `ProdutoController.explicacao_preco_adega`; lê o resultado do
  `CaixaController.itens`, não calcula um segundo preço nem grava observações explicativas no banco/cupom.
- `CaixaController.previa_cascos` consulta a venda sem gravar e compartilha `preco_por_quantidade_adega` com a
  reprecificação real, mantendo promoções e o mínimo por temperatura também na prévia.
- Economia usa o preço-base registrado. A faixa explicativa vem do **cadastro atual**, não de um retrato histórico.
  Não editar faixas durante um atendimento; para auditoria histórica exata, será necessário persistir a regra aplicada
  numa futura migração. Sem faixa disponível, a tela informa essa ausência em vez de inventar um mínimo.
- O diálogo preserva `floor(quantidade)` para cascos. Não proíbe uma bebida fracionada que o controller já aceite;
  apenas limita os cascos a inteiros. Não transforma troca em crédito de cliente.
- Não inclui NFC-e, promoção gelada por período, integração nova, compra automática ou estoque único entre caixas.

## Plano em fases

### Fase 1 — rápida (esta entrega)

Explicação de preço compartilhada; atalhos/prévia/validação de cascos Tk; visão Adega nos dois estoques;
testes de regressão e este guia. Aceite: todos os itens marcados como implementados na tabela funcionam sem alterar
totais, cancelamentos ou o fluxo dos demais perfis. Homologar com operador antes de instalar.

### Fase 2 — média

Reposição por giro e prazo (Top 1), paridade de cascos Qt, importação de atacado gelada e etiquetas.
Fazer um PR incremental por melhoria. Aceite: cálculo explicável, nenhuma compra automática,
dados insuficientes sinalizados e piloto de duas semanas comparado à sugestão atual.

### Fase 3 — avançada

Após decisões do dono: cancelamento parcial guiado, saldo de cascos por cliente, combos e múltiplas faixas.
Aceite: regras aprovadas por escrito, migrações versionadas, auditoria/estornos e testes de precedência de preços,
composição e estoque. Não publicar várias regras novas simultaneamente.

## Métricas de sucesso

Coletar uma semana de referência e duas semanas de piloto nos mesmos dias/horários. Metas são propostas,
não resultados já obtidos. Sem coletar dados pessoais de clientes.

| Métrica | Como medir | Meta inicial sugerida |
|---|---|---|
| Tempo de atendimento | Mediana e p90 do primeiro lançamento ao fechamento, separando balcão e entrega | Reduzir mediana em 15%, sem piorar p90 |
| Erro de preço | Vendas com correção por temperatura/faixa errada por 100 vendas; separar de desistência | Reduzir em 50% |
| Ruptura | Contagem diária de SKUs controlados sem estoque / SKUs controlados da Adega; anotar duração dos principais | Reduzir em 20% após ajustar mínimos |
| Perdas | Quantidade e custo dos descartes/quebras por semana, contra unidades vendidas e custo movimentado | Reduzir taxa em 10%, sem deixar de registrar perdas |
| Casco incorreto | Correções de casco por 100 vendas retornáveis, incluindo cancelamento esquecido | Reduzir em 50% |

Tempo e motivo de correção ainda exigem observação/amostragem operacional; não foi adicionada telemetria.
Ruptura e perdas podem ser conferidas pelos saldos e movimentos existentes. Não prometer redução só com mudança de tela.

## Próxima melhoria recomendada (Top 1)

**Problema:** o dobro do mínimo não acompanha giro e prazo de entrega, aumentando ruptura em picos e capital parado.

**Proposta técnica:** acrescentar ao `EstoqueController` uma consulta agregada de saídas líquidas de vendas/estornos
por produto em 7/14/30 dias, pelas unidades efetivamente movimentadas (incluindo fardos). Separar perdas de consumo
de venda. Calcular quantidade-alvo por média diária × (prazo do fornecedor + dias de segurança), subtrair saldo
e pedidos pendentes para evitar dupla compra e arredondar pela unidade de compra configurada.
Exibir janela, amostra e cálculo na prévia; manter dobro do mínimo como fallback explícito quando faltar histórico.
Qualquer prazo/unidade persistido exige migração em `src/database/esquema.py`. Aprovação humana obrigatória:
nenhum pedido ou movimento nasce só por consultar a sugestão.

**Impacto esperado:** menos ruptura e excesso de compra; medir pelas mesmas métricas do piloto, não por estimativa financeira.

**Esforço estimado:** 4–6 dias de desenvolvimento/testes mais duas semanas de piloto, após definição de prazo,
segurança e unidade de compra com o dono.

**Riscos:** histórico curto, períodos sem estoque subestimando demanda, sazonalidade, estornos fora da janela,
compra ainda não entregue, dupla contagem de fardos e consultas pesadas. Mitigar com fallback, aviso de amostra
insuficiente, testes de movimentos/estornos/composição e consulta agregada com medição antes de criar índices.

## Checklist de validação manual

- [ ] Em banco de teste, configurar bebida natural R$ 8,00, gelada R$ 10,00, atacado natural 6 por R$ 7,00
  e gelada 6 por R$ 9,00; vincular casco R$ 2,00 e habilitar agrupamento.
- [ ] No caixa Tk e Qt, lançar cinco naturais e mais uma: conferir faixa 6 e economia R$ 6,00; repetir gelada.
  Cancelar abaixo do mínimo e verificar restauração do preço. Três naturais + três geladas não atingem faixa.
- [ ] No Tk em 1180×678, selecionar a linha: explicação deve continuar legível fora da grade.
- [ ] No diálogo Tk de seis retornáveis, F2 deve mostrar R$ 0,00; F3, R$ 12,00; digitar 2 deve mostrar R$ 4,00.
  Digitar 7, -1 ou 1,5 deve impedir confirmação; Esc não lança nada.
- [ ] Confirmar dois cascos, verificar total e linhas independentes; cancelar bebida e conferir casco restante.
- [ ] Configurar promoção/atacado no casco e conferir que a prévia corresponde à variação dos itens de casco,
  inclusive quando uma nova unidade reduz o preço das anteriores. Conferir também fora do balcão.
- [ ] Nos dois estoques, alternar Geral/Adega, combinar Sem estoque/Repor com busca/grupo, conferir categorias,
  prioridades e totais do recorte. Conferir produto sem mínimo e produto sem controle.
- [ ] Conferir que pedido/lista continuam gerais; lançar entrada/perda/contagem e atualizar saldos.
- [ ] Abrir outro perfil e testar venda comum, pagamento e fechamento; conferir cupom na impressora da loja.

## Arquivos alterados e finalidade

- `src/controllers/produto_controller.py`: explicação reutilizável e cálculo compartilhado de preço por quantidade.
- `src/controllers/caixa_controller.py`: faixas atuais na consulta de itens, preservando produto excluído; prévia de cascos.
- `src/ui/caixa_ui.py`, `src/ui_qt/caixa.py`: exibem rótulo, regra e economia; detalhe legível no Tk e dica no Qt.
- `src/ui/adega_dialogos.py`: atalhos, prévia financeira e validação de cascos.
- `src/controllers/estoque_controller.py`: recorte Adega, categoria e prioridade com regras existentes de reposição.
- `src/ui/estoque_ui.py`, `src/ui_qt/estoque.py`: seletor de visão, resumo e identificação operacional.
- `tests/test_adega_regras.py`, `tests/test_adega_tk.py`, `tests/test_adega_qt.py`: regressão de preço, cascos e notebook.
- `tests/test_estoque.py`, `tests/test_qt_estoque.py`, `tests/test_ui.py`: recorte, filtros e prioridades.
- `docs/ADEGA.md`, `docs/ADEGA_MELHORIAS.md`: acesso ao plano e documentação técnica/funcional.
- `.ai/HANDOFF.md`: estado final e pendências para continuidade.
