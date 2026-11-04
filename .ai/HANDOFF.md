# Handoff — 04/11/2026

## Correção: shows automáticos e manuais juntos no acerto

- Usuário informou que havia shows anteriores ao automático e pediu manter lançamento manual mesmo com Quartos ligado.
- `DialogoAcerto`: mantém a contagem automática protegida e adiciona **Shows manuais / anteriores**. Exibe automáticos + manuais = total; soma ao pagamento e às comissões usando a tarifa escolhida (50/60), vale, Pix e dinheiro. Campo manual funciona também com zero automáticos. Não repetir shows já registrados ou pagos.
- Controlador aceita total maior que os automáticos, mas recusa total menor. Valida separadamente a quantidade manual, inclusive negativos/frações/texto e limite total 999. Mantém verificação dos IDs e consumo atômico dos shows dos quartos; acerto repetido ou desatualizado continua recusado.
- Sem mudança de esquema. Quantidade manual histórica pode ser derivada do total do acerto menos os shows vinculados; recibo misto mostra as duas origens.
- Validação desta correção: 183 testes aprovados (`test_shows_quartos`, `test_comissao_garotas`, `test_acerto_garota_shows`, `test_qt_comissao`, `test_qt_comanda_garota_vazia`), incluindo legado só manual, misto 50/60, vale/Pix, recibo/turno, campos inválidos, concorrência e pagamento repetido. `git diff --check` sem erros. Pronta para publicação na main no fluxo solicitado pelo usuário.

## Integração anterior

- Main estava em `890d430`: cada 30 minutos contratados gera um show ao iniciar/acrescentar tempo. Esquema 36, tabela shows_quartos, sem backfill de históricos. Relógio/liberação não geram shows. Tempo e shows atômicos; pagamento vincula IDs ao acerto. Limpeza de acerto não reabre pendências.
- Iniciar quarto pela tela exige profissional cadastrada e tempo explícito (30 min, 1h, 1h30 etc.). Painel atualiza comanda imediatamente. Formulário do acerto tem rolagem e botão Pagar sempre visível.
- Correções anteriores publicadas: `37c2327` (corte dos quartos), `1c9c289` (escolha do tempo). Suíte completa da integração anterior: 2340 testes, seis pulados Windows/PostgreSQL; 131 testes dos ajustes finais aprovados.
- Ambiente: Python 3.12, `.venv`, dependências com hashes. Instalação/inicialização salvas no rascunho do ambiente. Não houve geração de instalador nesta tarefa.

## Pendências anteriores

- Homologar no Windows da loja, incluindo central, sincronização/licenças, periféricos e atualização automática.
- Ficha/crédito do produto local código 31 continua pendente; não introduzir regra global pelo código.
- Credenciais de cobrança/e-mail fora do chat. Outros detalhes no histórico deste arquivo.
