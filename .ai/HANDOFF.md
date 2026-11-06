# Handoff — Central do fornecedor publicada — 06/11/2026

## Entrega

- PR #55 integrado: https://github.com/GodFather-byte/PDV-CASA-2.0/pull/55.
- Código publicado no Render: `78bd596c5d1f6d85a17fa33d3db7db2682704ccc`.
- Painel: https://willpdv-nuvem-6sp0.onrender.com/central/.
- Render: GodFather's workspace (`tea-d3ekasbuibrs73caqdog`), serviço `willpdv-nuvem` (`srv-dbf5untg1s2s73ejihdg`), deploy `dep-dbmt945ckfvc739177p0` confirmado live. Nenhuma variável, segredo ou plano de infraestrutura foi alterado.
- Worktree: `C:\Users\ITAUTEC\source\willpdv-central`. A cópia antiga do OneDrive está 107 commits atrás da base desta entrega e contém um rascunho Asaas não publicado; não reaproveitá-lo.

## O que está implementado

- Central exclusiva em `/central/`; rotas `/v1/fornecedor/*`. As rotas antigas `/v1/central/*` da ponte foram preservadas.
- Login com o `PDV_API_TOKEN` já configurado no servidor, sessão HttpOnly/SameSite Strict/Secure em HTTPS, oito horas, hash persistido e revogação por logout/rotação do token. CSRF, limite de tentativas por processo e respostas sem cache. Segredos não ficam em localStorage nem na URL.
- Lojas existentes, cadastro com token exibido uma vez, mensalidades, cobranças paginadas, conciliação no Mercado Pago, ativação/desativação, plano mensal, validade manual para lojas sem plano e emissão assinada com a chave existente. Ações auditadas.
- Transferência explícita da emissão por loja: confere a chave da nuvem, preserva maior prazo e validade anterior do plano, mantém tokens/ponte e renova nas consultas normais ou de caixas individuais. Sem transferência, o comportamento antigo é preservado.
- Suporte: último envio dos caixas, versões quando informadas, erros, chamados e diagnóstico em texto para uso externo no Codex/Claude Code. Aprovação/revogação de caixas individuais e confirmação da licença aplicada.
- Atualizações por manifesto assinado, HTTPS, confirmação de edição/canal; distribuição pela infraestrutura já existente. Versão/edição acrescentadas ao retrato dos caixas atualizados.
- Apenas tabelas novas na nuvem. Esquema SQLite local e dados de vendas não foram alterados. Guia: `docs/CENTRAL_FORNECEDOR.md`.

## Validação concluída

- CI do PR: https://github.com/GodFather-byte/PDV-CASA-2.0/actions/runs/42222160715. Cinco jobs aprovados: PostgreSQL 16 e suítes completas Windows/Linux com Python 3.10/3.12. Head validado `626cba5`.
- Rodadas locais: 90 testes (1 ignorado), 109 testes e 13 testes centrais aprovados; teste específico de manifesto inválido também passou. Há sobreposição; não somar como casos distintos.
- Node `--check`, compilação Python e `git diff --check` passaram. Página local respondeu HTTP 200; os testes usaram bancos temporários e sementes fictícias.
- Produção: `/v1/versao` confirmou o commit esperado; `/central/`, JS e CSS retornaram 200 com no-store; `/v1/fornecedor/lojas` anônimo retornou 401; login com credencial fictícia por HTTPS retornou 401, comprovando que a verificação de HTTPS não bloqueia o proxy atual. Não foi feito login com segredo real.
- CUA e Node REPL expiraram; revisão visual em celular/desktop permanece pendente. A prévia temporária na porta 8765 foi encerrada.

## Próximos passos com o usuário

- Entrar no painel com a credencial administrativa já existente no Render. Não solicitar segredos pelo chat.
- Nenhuma loja real foi transferida, nenhum pagamento foi gerado/conferido em produção, nenhum pacote de atualização foi publicado e nenhum programa foi desinstalado por esta entrega.
- Antes de retirar Will Licenças: backup externo da chave/históricos, transferir e testar uma loja real com a central local fechada; confirmar renovação no caixa e só então repetir nas demais.
- Usuário ofereceu revisão externa do Claude; nenhum relatório foi recebido antes da publicação. Incorporar eventuais achados numa nova alteração, sem desfazer as entregas anteriores.
- Diagnóstico/chamados/atualização são o suporte desta versão. Não há shell, controle de tela, execução automática de IA ou reparo arbitrário do banco. Controle integral do Windows depende de solução instalada/autorizada na loja.
- Pacotes são por edição/canal; não há rollout por loja nesta entrega. Caixas sem o atualizador precisam de instalador inicial. Publicação não prova instalação concluída.
- Este commit de documentação usa skip ci/skip render: o código executável já foi aprovado/publicado e não mudou; `/v1/versao` permanece no commit de código acima.

## Continuidade anterior

Preservados ajustes de estoque/quartos/shows, migração antiga de itens e formulário Linux da base `59f1715`. Não desfazer `7700458`, `2103b7a` ou `fb13f93`. Ajuste de impressora `9324c64` é trabalho separado. Homologar periféricos e escala no Windows real.
