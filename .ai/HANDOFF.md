# Handoff — 06/11/2026

## Will Adega para venda (segunda, 09/11)

Branch `claude/cloud-environment-setup-6auvo5`, dois commits sobre a main `59f1715`:

- `14ab336` **E&A Superações virou Will Adega.** Chave da edição `willadega` (não há mais `ea_superacoes`: o
  usuário confirmou que não existe loja instalada com a edição antiga). Nome "Will Adega", marca "WILL ADEGA",
  `WillAdega.exe`, dados em `%LOCALAPPDATA%\WILL-ADEGA`, `instalador/WillAdega.iss` com AppId novo, atalho
  `iniciar_will_adega.bat`, logo/ícone/assistente em vinho (`tools/gerar_logos.py`, função `gravar_adega`).
  Tela de entrada usa a marca da edição; o aviso "Piloto Qt" ficou só no WillPDV (`Edicao.aviso_entrada`).
  Licença emitida para `willadega` no licenciador (lista vem de `EDICOES`). Release fixa continua `ultima-versao-adega`.
- `1f78aca` **Reposição pelo giro evoluída** (`EstoqueController.reposicao_giro`): janela 7/14/30, prazo de entrega
  + cobertura, desconta pedidos não entregues dos últimos 30 dias, unidade inteira se o produto não aceita fração,
  equivalência em fardos, fallback dobro do mínimo sem venda, `explicacao` por produto. Parâmetros em `config`
  (`giro_janela_dias`, `giro_prazo_dias`, `giro_cobertura_dias`), sem migração. Tela `DialogoGiro`.
- Suíte completa local: 2371 testes OK (6 pulados), Node 9/9.

## Pendências

- Conferir o CI do PR (build Windows gera `WillAdega-Setup-*.exe` e roda o autoteste procurando "Will Adega").
- Antes de vender: gerar o instalador pelo CI, instalar num Windows limpo, emitir licença `willadega` e fazer uma venda
  completa com leitor, impressora e gaveta (checklist em `docs/ADEGA.md`).
- Reposição: prazo por fornecedor e unidade de compra por produto ficaram de fora (exigem migração); decidir no piloto.
- Revisão da branch `codex/central-fornecedor` (Codex): 5 problemas relatados ao usuário, incluindo licença emitida
  pela nuvem sem a edição (perderia a Will Adega). Lá a chave ainda é `ea_superacoes`: ao fazer rebase, trocar.

## Continuidade (anterior)

- Contas Qt com rótulos acima dos campos para caber em 1280×680 (commit `59f1715`); estoque permite venda sem saldo
  por padrão, quartos 0 a 4 operadores; documentação em `docs/OPERACAO_CAIXA_E_TELAS.md`.
- `9324c64` na branch work é ajuste local de impressora separado; Codex no PC ajusta impressora, evitar sobreposição.
- Ambiente: Python 3.12 (venv `/opt/pdv-venv` na nuvem), Qt offscreen, Tk requer Xvfb. Ficha código 31 pendente.
