# Handoff — 06/11/2026

## Correção das duas falhas Linux no GitHub

- Execução `42200090513` do commit `7700458`: Windows 3.10/3.12 e PostgreSQL passaram. Linux 3.10/3.12 falharam somente em `JanelaContas`: largura mínima 1282 para área cliente 1280. Instalador e nuvem passaram.
- `src/ui_qt/contas.py`: rótulos acima dos campos no formulário e filtros (`QFormLayout.WrapAllRows`), removendo a soma horizontal de rótulo + campo em cada coluna. Não reduz limite do teste, não oculta controles nem muda regras financeiras.
- Novo teste com DejaVu Sans, Liberation Sans e sans-serif confere área 1280×680, campos/ações visíveis e dentro da janela e espaço da tabela. 39 testes de painéis responsivos e contas aprovados; `git diff --check` limpo. Log `/tmp/pdv-contas-fontes.log`.
- Usuário já autorizou publicar tudo; esta correção integra a mesma entrega. Publicar na main e conferir os jobs Linux do novo commit.

## Entrega publicada na main `7700458`

- Estoque: `permitir_venda_sem_estoque` ligada por padrão, inclusive em bancos existentes. Venda pode deixar saldo negativo com auditoria; estorno exato. Opção desligada restaura bloqueio. Saídas/ajustes manuais continuam validados.
- Quartos: módulo ligado permite operadores ativos 0 a 4 em qualquer turno, independentemente do mínimo antigo. Configurações administrativas restritas. Paginação de oito quartos, Q + número e avisos considerando todos.
- Qt: menu agrupado, indicadores em abas, controles compactos e janelas na área útil. Caixa sem rolagem geral; busca em popup. Acerto em duas colunas e filtros de relatórios em grade. Listas/históricos continuam rolando. Referência autorizada 1366×768; testes em área cliente 1280×680.
- Documentação: `docs/OPERACAO_CAIXA_E_TELAS.md`. Verificar no Windows real a escala de tela e periféricos.
- Teste de pagamento simultâneo dos shows: preparar conexões antes de disputar pagamento; cada conexão nasce/usa/fecha na própria thread. Barreira só no pagamento e `ExitStack` para limpeza. Mantém um pago, outro recusado e saída única R$ 50. Corrigiu o erro anterior `BrokenBarrierError` no Windows 3.10; os dois jobs Windows passaram na execução acima.
- Validação anterior: 133 testes locais de integração da entrega e 25 repetições da concorrência aprovados. CI anterior completo teve apenas a falha de largura descrita acima nos dois Linux (2363 casos em cada job). Não confundir mensagens simuladas de backup e notificação no log com falhas reais.

## Continuidade

- `2fc841e`: comprovantes de comissão/acerto apenas número/nome, sem "Garota", assinatura genérica; cálculos/registros mantidos.
- `2103b7a`: migração v17 de itens antigos de 14 para DDL de 20 campos por nome, preservando defaults/backup/rollback. Não apagar banco da loja.
- `fb13f93`: shows automáticos dos quartos + manuais/anteriores no acerto (50/60), esquema 36, sem backfill e sem repetição dos IDs pagos.
- `9324c64` na branch work é ajuste local de impressora separado; Codex no PC ajusta impressora, evitar sobreposição.
- Tabela de 160 sugestões em `/workspace/entregas/bar_adega`; preencher preços zerados. Consulta online GTIN não implementada por escolha do usuário.
- Ambiente Python 3.12/.venv; Qt offscreen e Tk requer Xvfb. Ficha código 31 pendente; credenciais fora do chat.
