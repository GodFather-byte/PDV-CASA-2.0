# HANDOFF

## Último trabalho

Melhorias Adega e CI pós-merge no PR #11:

- Workflows automáticos somente em `push` na `main`, com execução manual mantida.
  Nuvem mantém filtro de caminhos; tags de versão do instalador só por execução manual.
- Pedido/lista Geral preservados; Adega combina classificação, situação, grupo e busca.
- Estoque Tk/Qt mostra cobertura: saldo não negativo / consumo líquido médio diário
  de vendas e estornos nos últimos 30 dias; sem consumo ou controle, indisponível.
- Classificação normaliza famílias de grupo/subgrupo e prefixos descritivos cautelosos.
  Grupo Adega permite inclusão explícita; o recorte continua indicativo, não fiscal.
- Esquema v24 adiciona `itens_venda.regra_preco_json`, capturado no lançamento e
  mantido na reprecificação. Explicação histórica usa o retrato, não o cadastro atual.
  Itens legados sem retrato não recebem promoção/faixa inventada.

## Validação

- Três workflows: YAML válido; gatilhos conferidos como `push` em `main` e manual.
- Auditoria de preços/migração: 172 testes aprovados; regressões disponíveis ampliadas
  chegaram a 887 aprovados e 205 ignorados, sem falhas nos módulos disponíveis.
- Estoque e regressões de domínio: 199 aprovados, 2 pulados.
- Massa de 5.000 produtos/movimentos: sem consultas por produto; painel, resumo e
  lista usam 5 SELECTs no total. Resumo/lista não consultam histórico de consumo.
- Com 305 mil movimentos, retirar consultas desnecessárias reduziu o conjunto
  de 477 para 303 ms em SQLite em memória; medição sintética, sem renderização.
- Tk/Qt e módulos dependentes de PIL não executados neste sandbox: dependências ausentes.
  `test_adega_cadastro` tem `NameError` preexistente ao importar sem Qt; não alterado.

## Migração e rollback

Backup consistente antes da atualização. A abertura de banco v23 cria cópia
`.antes-migracao-v23-*.bak` e migra para v24. Para voltar ao executável anterior,
pare o PDV, preserve o banco atual e restaure a cópia pré-migração; não reduza
`user_version` manualmente. Vendas posteriores ao backup exigem reconciliação.

## Pendências

- Homologar visualmente Tk/Qt e impressão em cópia do banco da loja.
- Acompanhar CI após merge; não há mais checks automáticos em PR.
- Se a proteção da `main` exigir checks de PR antigos, administrador deve ajustar
  a configuração para não bloquear merges aguardando execuções removidas.
- Cobertura não muda a sugestão do dobro do mínimo nem automatiza compras;
  não estima prazo do fornecedor ou sazonalidade.
