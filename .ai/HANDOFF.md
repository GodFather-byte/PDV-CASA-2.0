# Handoff — Central do fornecedor — 06/11/2026

## Escopo autorizado

O usuário pediu um painel próprio na nuvem para acompanhar lojas, pagamentos e licenças e prestar suporte pelo celular/PC com auxílio de Codex e Claude Code. Base atualizada `59f1715`; worktree separado em `C:\Users\ITAUTEC\source\willpdv-central`, branch `codex/central-fornecedor`. Não reutilizar o rascunho Asaas da cópia antiga em OneDrive, 107 commits atrás.

## Implementação

- `/central/`: interface responsiva do fornecedor; `/v1/fornecedor/*`: sessão HttpOnly/SameSite Strict, Secure em HTTPS, validade 8h, hash persistido e revogação por logout/rotação de `PDV_API_TOKEN`. Limite de login por processo, proteção CSRF e respostas sem cache. Não usa localStorage para segredos.
- Lojas existentes, cadastro com token exibido uma vez, situação/validade, planos Mercado Pago e cobranças paginadas, conciliação, ativação/desativação, validade manual para loja sem plano e emissão de código usando a chave existente da nuvem. Ações administrativas auditadas.
- Transferência explícita da emissão por loja: confere chave, preserva prazo e validade anterior do plano, mantém tokens e ponte. `renovar_ponte` só age em lojas transferidas; renova na consulta de licença normal ou do caixa individual. Não reduz o prazo já publicado.
- Suporte: erros já enviados pelos caixas, último contato, chamados, diagnóstico em texto para revisão/uso externo com IA. Aprovação/revogação de caixas individuais e confirmação da licença aplicada. Sem shell remoto, tela remota, API de IA ou reparo automático do banco.
- Atualizações: publicar manifesto assinado pelo mecanismo existente; HTTPS e confirmação de edição/canal. Não confirma instalação. Versão/edição passaram a ser enviadas no retrato de caixas atualizados.
- Tabelas novas somente na nuvem; esquema SQLite local preservado. `/v1/central/*` da ponte antiga não foi sobrescrito.
- Guia `docs/CENTRAL_FORNECEDOR.md`, mapa e CI atualizados. Testes do fornecedor incluídos também no PostgreSQL do CI.

## Validação

- 90 testes de central/ponte/cobrança/assinatura: aprovados, 1 ignorado. Foram seguidos de 13 testes da central aprovados após incluir caixa individual.
- JavaScript passou em `node --check` (Node do Cursor); HTML com IDs únicos; `git diff --check` e compilação Python passaram.
- API local e página `/central/` responderam HTTP 200 em ambiente temporário com lojas fictícias. Ferramenta de navegador e Node REPL expiraram; não alegar revisão visual completa.
- Rodada adicional de nuvem, renovação, atualização e painel: 109 testes aprovados, sem falhas.
- Uma chamada anterior usou nomes inexistentes `test_ponte_nuvem` e `test_cobranca_mercadopago`: falhou somente nesses dois imports. Os nomes corretos são `test_ponte_backend` e `test_cobrancas_mercadopago`, aprovados na rodada de 90.
- Testes usam bancos temporários e sementes fictícias; não migram lojas reais, não cobram clientes, não publicam pacotes de correção nem alteram credenciais reais.

## Publicação e limites

- Render confirmado: GodFather's workspace, serviço `willpdv-nuvem`, branch main, URL `https://willpdv-nuvem-6sp0.onrender.com`. Auto deploy ligado. Confirmar o commit via `/v1/versao` após publicar.
- Usuário ofereceu revisão do Claude; orientar a revisar a branch/diff sem editar em paralelo. Ainda não recebida revisão.
- Antes de desinstalar Will Licenças: backup externo da chave/históricos, migrar e testar uma loja real com o PC do fornecedor desligado e só então repetir nas demais. Não desinstalado nenhum programa.
- A versão do PC do cliente precisa incluir o atualizador para receber pacotes; caixas antigos exigem instalador inicial. Atualizações são por edição/canal, sem rollout por loja nesta entrega.
- Controle integral do Windows exige solução de acesso remoto instalada e autorizada; esta entrega trata suporte dentro do WILLPDV.

## Continuidade anterior preservada

Main base já inclui ajustes de estoque, quartos, shows, migração antiga de itens e formulário de contas Linux. Não desfazer `59f1715`, `7700458`, `2103b7a` ou `fb13f93`. Ajuste de impressora `9324c64` é trabalho separado. Validar periféricos e escala no Windows real. Segredos permanecem fora do chat/git.

## Revisão e publicação

PR #55 aberto: https://github.com/GodFather-byte/PDV-CASA-2.0/pull/55. CI do GitHub em andamento; não integrado à main nem publicado nesta etapa. Revisão visual ainda pendente por indisponibilidade da ferramenta de navegador.
