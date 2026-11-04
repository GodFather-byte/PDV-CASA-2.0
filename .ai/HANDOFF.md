# Handoff — 04/11/2026

## Correção do corte dos quartos no caixa

- `src/ui_qt/caixa.py`: produtos e pagamento ficam em uma área de rolagem independente, com quartos abaixo. A altura mínima anterior do caixa com sete quartos era 910 px e cortava o painel em monitores de 768 px. A busca de produtos não deve aumentar a janela nem empurrar os quartos para fora.
- `tests/test_quartos.py`: regressão busca e lança produto com sete quartos em 1366×768 e 1280×720; verifica limites e tamanho do painel.
- Validação Linux/PySide6 offscreen: 56 testes aprovados (`tests.test_quartos`, `tests.test_qt_caixa`, `tests.test_caixa_tela_pagamento`). `git diff --check` sem erros. Validar visualmente no Windows da loja; não houve geração de instalador nesta tarefa.
- Ambiente de desenvolvimento: Python 3.12, `.venv`, dependências fixadas com hashes. Instruções de instalação e inicialização salvas no rascunho do ambiente. No onboarding anterior, suíte completa: 2327 testes, seis pulados (Windows/PostgreSQL), sem falhas.

## Continuidade anterior

- Controle de quartos por profissional e histórico já estava no checkout; não se alteraram regras financeiras, esquema ou controladores nesta correção.
- Teste imediato da central em Configurações e sincronização/licenças aguardam homologação na loja.
- Ficha/crédito do produto local código 31 continua pendente de definição e implementação; não introduzir regra global pelo código.
- Qt, periféricos reais, atualização automática e instalação Windows precisam de homologação no balcão. Credenciais de cobrança/e-mail devem ser fornecidas fora do chat.
- Consulte o histórico deste arquivo no Git para detalhes anteriores sobre painel, cardápio, devoluções e atualização automática.
