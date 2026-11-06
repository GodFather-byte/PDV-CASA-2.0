# Handoff — 06/11/2026

## Correção do teste de concorrência no GitHub

- Workflow `Testes`, execução 42150592006, job Windows/Python 3.10: único erro em `test_duas_conexoes_nao_pagam_os_mesmos_shows`, `BrokenBarrierError` ao esperar 10s pela segunda conexão. Linux 3.10/3.12, Windows 3.12 e PostgreSQL passaram; instalador e publicação da nuvem passaram.
- Teste agora abre as duas conexões sequencialmente antes de disparar os pagamentos simultâneos. Cada conexão continua criada, usada e fechada em sua própria thread. A barreira sincroniza apenas a operação financeira, mantendo a disputa real e todas as asserções: um acerto pago, outro recusado e uma única saída de R$ 50.
- `ExitStack` garante fechamento das conexões antes de encerrar seus executores, inclusive se a preparação ou pagamento falhar. Nenhuma mudança no código financeiro ou nos timeouts do banco.
- Validação nesta branch isolada: 122 testes de shows/comissões/acerto Qt aprovados; teste de concorrência repetido 25 vezes com sucesso; `git diff --check` limpo. Logs `/tmp/pdv-ci-isolado.log` e `/tmp/pdv-ci-concorrencia-repetida.log`. Validação Windows depende do CI do PR.
- Esta branch parte de `2fc841e` e não inclui o commit local `389458a` de estoque/telas/quartos, que permanece em `fix/migracao-banco-antigo` aguardando publicação específica.
- Publicação planejada como PR para revisão e execução do CI, sem merge direto na main.

## Continuidade

- Main anterior `2103b7a`: corrige migração v17 do banco antigo (14 campos dos itens para DDL atual de 20) copiando campos pelo nome, sem perder os defaults novos. Backup e rollback preservados. 85 testes aprovados. Não apagar banco da loja; instalar executável com correção.
- `9324c64` continua na branch work como ajuste local de impressora; não foi incluído na publicação da migração. Codex no PC do usuário está ajustando impressora; evitar sobrepor arquivos.
- `fb13f93`: shows automáticos dos quartos + manuais/anteriores no acerto (50/60); esquema 36, sem backfill, IDs vinculados ao acerto evitam repetição. Seleção de tempo/profissional e correção de corte das telas já publicadas.
- Tabela de 160 sugestões em /workspace/entregas/bar_adega (fora do checkout), CSV/XLSX validados; preencher preços zerados antes de importar. Usuário preferiu tabela; consulta online GTIN não implementada.
- Ambiente Python 3.12/.venv. Gerar/homologar instalador Windows e periféricos. Ficha código 31 pendente; credenciais fora do chat. Demais detalhes no histórico deste arquivo.
