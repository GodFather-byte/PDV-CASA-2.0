# Handoff — 04/11/2026

## Shows dos quartos integrados ao acerto

- Regra confirmada pelo usuário: cada 30 minutos contratados gera um show imediatamente, ao iniciar ou acrescentar tempo. No acerto escolhe R$ 50 ou R$ 60 por show (tarifas de `show_valores`), somando às comissões. Relógio e liberação não geram shows.
- Esquema 36: `shows_quartos` registra origem, profissional, quantidade e acerto que consumiu os shows. Sem backfill de históricos antigos, que podem ter sido pagos manualmente. Referência histórica `acerto_id` sem FK: limpeza do acerto não pode reabrir pendências.
- Tempo e lançamento dos shows são atômicos. Pagamento vincula as pendências na mesma transação da sangria/acerto. A tela transmite os IDs vistos; mudança de quantidade ou pagamento por outra conexão exige reabrir o acerto.
- Com Quartos ligado, quantidade no acerto é automática e não editável, inclusive zero após pagar. Valores de comissão, shows, vale, Pix e dinheiro são separados. Conteúdo tem rolagem e Pagar fica fora da rolagem. Cartões/comanda/lista mostram os shows; recibo identifica origem. Mudanças do painel atualizam a comanda imediatamente.
- Diálogo de início exige código de profissional cadastrada para vincular os shows. Controlador mantém compatibilidade com chamadas antigas sem profissional; estas não geram shows. Tempos são convertidos em meias horas completas usando o bloco congelado no uso.
- Testes novos: `tests/test_shows_quartos.py` cobre início, acréscimo, frações, tarifas 50/60, comissão/vale/Pix/recibo/turno, pagamento único, concorrência com duas conexões, rollback, migração, reabertura, formulário e integração de tela.
- Validação: suíte completa executou 2340 testes sem falhas, seis pulados (Windows/PostgreSQL); após ajustes finais de formulário/limpeza de widgets, 131 testes de shows, quartos, comissões Qt e cartões passaram sem traceback. Também passaram 342 testes de regressão de caixa, comissões, acerto e app durante a implementação. `git diff --check` sem erros. Homologar no Windows da loja antes de operar.

## Alterações anteriores

- `37c2327` publicado na main: rolagem independente de produtos/pagamento preserva os quartos em telas baixas.
- `1c9c289` local: Q3 + Enter exige escolha explícita do tempo (30 min, 1h, 1h30, 2h, 3h e demais durações); sem meia hora automática.
- Esta tarefa não publica na main nem gera instalador. Preservar os commits locais ao continuar.
- Ambiente: Python 3.12, `.venv`, dependências com hashes, instalação/inicialização salvas no rascunho do ambiente.

## Pendências anteriores

- Homologar central, sincronização/licenças, periféricos, atualização automática e instalação Windows na loja.
- Ficha/crédito do produto local código 31 continua pendente; não introduzir regra global pelo código.
- Credenciais de cobrança/e-mail fora do chat. Detalhes anteriores de painel, cardápio, devoluções e atualização automática no histórico deste arquivo.
