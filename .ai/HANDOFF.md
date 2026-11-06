# Handoff — 06/11/2026

## Venda sem saldo, quartos para todos os caixas e telas compactas

- Pedido: continuar vendendo quando o estoque acaba, eliminar a rolagem geral dos painéis principais e mostrar quartos nos caixas da manhã/noite em todos os níveis. Referência autorizada: 1366×768.
- Estoque: nova configuração `permitir_venda_sem_estoque`, ligada por padrão inclusive em bancos existentes pelas sementes. A venda registra saldo negativo e auditoria `venda_sem_estoque`; cancelar estorna a quantidade exata. Composições fracionadas seguem a mesma regra. Administrador pode restaurar o bloqueio desligando a opção; ajustes manuais continuam validados.
- Acesso: `util_quartos` permite operadores ativos de níveis 0 a 4 quando `usar_quartos` está ligado, inclusive se havia mínimo antigo 4. Configurações administrativas continuam restritas. Validações de sessão e módulo permanecem nas telas.
- Interface PySide6: menu agrupado, indicadores em abas, tema compacto, abertura limitada à área útil do monitor. Caixa sem rolagem geral de produtos/pagamento; sugestões em popup sem empurrar os quartos. Acerto de comissão/shows em duas colunas; relatórios com filtros em grade. Listas e históricos mantêm rolagem quando os dados crescem.
- Quartos paginados de oito em oito no caixa e painel completo; atalhos Q + número e avisos consideram todos os quartos.
- Documentação: `docs/OPERACAO_CAIXA_E_TELAS.md`. Novos testes em `tests/test_operacao_responsiva.py` cobrem saldo, estorno, composição, opção estrita, níveis, inativo/módulo desligado, busca, pagamentos, comissão, 50 quartos e layout de área cliente 1280×680.
- Validação: suíte completa executou 2363 testes em 328s, com 2 falhas/1 erro exclusivamente porque o Xvfb :98 encerrou (central/licenciador), mais 24 pulados. Após abrir :99, os 49 testes desses módulos passaram, incluindo os 18 gráficos antes pulados e os três casos afetados. Resultado consolidado: 2357 casos Python aprovados; 6 dependem de Windows/PostgreSQL externo. Node: 2 testes aprovados. Testes direcionados finais: 83 de painéis/acerto/relatórios/acessos e 51 de configuração/tela cheia/layout aprovados. `git diff --check` limpo. Logs em `/tmp/pdv-operacao-completo-final.log`, `/tmp/pdv-tk-verificacao.log` e `/tmp/pdv-operacao-node.log`.
- Alterações locais ainda não publicadas na main. Não foi gerado instalador Windows nesta tarefa; conferir no caixa real, especialmente escala de tela do Windows.

## Continuidade

- Main `2fc841e`: comprovantes de comissão/acerto com apenas número/nome, sem a palavra "Garota", e assinatura genérica. Cálculos e registros mantidos. 212 testes direcionados aprovados naquela entrega.
- `2103b7a`: migração v17 do banco antigo (14 campos para DDL atual de 20) copia campos pelo nome e preserva defaults, backup e rollback. Não apagar banco da loja.
- `fb13f93`: shows automáticos dos quartos + manuais/anteriores no acerto (50/60); esquema 36, sem backfill, IDs vinculados ao acerto evitam repetição.
- `9324c64` continua na branch work como ajuste local de impressora, fora destas alterações. Codex no PC do usuário está ajustando a impressora; evitar sobreposição.
- Tabela de 160 sugestões em `/workspace/entregas/bar_adega`, fora do checkout; preencher preços zerados antes de importar. Consulta online GTIN não implementada por escolha do usuário.
- Ambiente Python 3.12/.venv; testes Qt offscreen e Tk com Xvfb :99 (:98 encerrou). Homologar instalador Windows/periféricos. Ficha código 31 pendente; credenciais fora do chat.
