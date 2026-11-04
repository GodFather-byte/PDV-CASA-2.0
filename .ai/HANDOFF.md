# Handoff — 04/11/2026

## Escolha explícita do tempo dos quartos

- `src/ui_qt/quartos.py`: Q3 + Enter abre o diálogo com Tempo sem seleção. Escolher uma duração habilita Confirmar tempo. Enter sem escolha não inicia 30 minutos automaticamente.
- Atalhos: um, dois, três, quatro e seis blocos (30 min, 1h, 1h30, 2h, 3h na configuração padrão). Lista permite os demais tempos dentro do limite do controlador. Respeita minutos por bloco configurados e limite restante ao adicionar tempo.
- Mantidos código/nome da profissional e regras de início/adicional do controlador; nenhuma mudança financeira ou no banco.
- Testes exercitam Q3 + Enter com diálogo real, cinco durações, cancelamento, bloqueio de Enter sem escolha e configuração diferente de bloco. Validação: 58 testes aprovados (`tests.test_quartos`, `tests.test_qt_caixa`, `tests.test_caixa_tela_pagamento`). Falta homologação visual no Windows da loja.

## Correção anterior publicada na main

- Commit 37c2327: área de produtos/pagamento com rolagem independente preserva quartos visíveis em telas 1366×768 e 1280×720. Antes exigia altura mínima de 910 px. Não houve geração de instalador.
- Ambiente: Python 3.12, `.venv`, dependências com hashes. Instalação e inicialização salvas no rascunho do ambiente. Onboarding: 2327 testes, seis pulados (Windows/PostgreSQL), sem falhas.

## Pendências anteriores

- Homologar Qt, central/sincronização/licenças, periféricos, atualização automática e instalação Windows na loja.
- Ficha/crédito do produto local código 31 continua pendente de definição e implementação; não introduzir regra global pelo código.
- Credenciais de cobrança/e-mail devem ser fornecidas fora do chat. Detalhes anteriores sobre painel, cardápio, devoluções e atualização automática estão no histórico deste arquivo.
