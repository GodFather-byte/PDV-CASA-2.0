# Handoff — 06/11/2026

## Will Adega para venda (segunda, 09/11)

Branch `claude/cloud-environment-setup-6auvo5` (PR #56), com a main `e364e2d` (central do fornecedor) incorporada:

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
- **Foto real do produto** (pedido do usuário): tabela `produto_fotos` (esquema v37, foto no banco, entra no backup),
  `FotoProdutoController` (normaliza JPEG 480/160 px, limites 8 MB/40 Mpx; busca no Open Food Facts só em
  `*.openfoodfacts.org` via https, sem redirecionamento), aba Foto no cadastro, foto do último item no caixa (coluna do
  pagamento, some com a venda vazia) e cardápio (endereço https ou miniatura embutida com orçamento de 1,5 MB).
- Suíte completa local: 2371 testes OK (6 pulados), Node 9/9.

## Pendências

- **Antigravity (backend):** `backend/cardapio.py` ganhou edição pontual em `_url` para aceitar
  `data:image/jpeg;base64` até 12000 caracteres (miniatura da foto de arquivo). Publicar a nuvem para o cardápio mostrar
  essas fotos; sem isso, só as fotos vindas da internet aparecem.

- Conferir o CI do PR (build Windows gera `WillAdega-Setup-*.exe` e roda o autoteste procurando "Will Adega").
- Antes de vender: gerar o instalador pelo CI, instalar num Windows limpo, emitir licença `willadega` e fazer uma venda
  completa com leitor, impressora e gaveta (checklist em `docs/ADEGA.md`).
- Reposição: prazo por fornecedor e unidade de compra por produto ficaram de fora (exigem migração); decidir no piloto.
- **Central do fornecedor (já na main, PR #55):** a revisão do Claude achou 5 problemas, ainda não corrigidos. O mais
  grave para a Will Adega: a nuvem assina licença sempre como WillPDV (`backend/licencas_fornecedor.py` em
  `renovar_ponte`, `backend/central_fornecedor.py` em `emitir_licenca` e o `GET /v1/licenca` antigo), então loja Will Adega
  que renove pela nuvem recebe código que o caixa recusa. Decidir com o usuário onde guardar a edição da loja na nuvem.
  Os outros: limite de login por IP do proxy (bloqueio global), validade manual que reduz prazo e validade acima de
  36500 dias que derruba a consulta de licença.

## Central do fornecedor (Codex, main `78bd596`)

- Publicada no Render (`/central/`, rotas `/v1/fornecedor/*`); guia em `docs/CENTRAL_FORNECEDOR.md`. Login com
  `PDV_API_TOKEN`, sessão HttpOnly com CSRF; lojas, cobranças, transferência explícita da emissão para a nuvem,
  suporte (erros, chamados, diagnóstico) e atualização por manifesto assinado. Só tabelas novas na nuvem.
- Nenhuma loja real foi transferida nem pacote publicado. Antes de retirar o Will Licenças: backup da chave, transferir
  e testar uma loja real com a central local fechada. Revisão visual em celular/desktop pendente.
- Worktree do Codex: `C:\Users\ITAUTEC\source\willpdv-central` (a cópia antiga do OneDrive não deve ser reaproveitada).

## Continuidade (anterior)

- Contas Qt com rótulos acima dos campos para caber em 1280×680 (commit `59f1715`); estoque permite venda sem saldo
  por padrão, quartos 0 a 4 operadores; documentação em `docs/OPERACAO_CAIXA_E_TELAS.md`.
- `9324c64` na branch work é ajuste local de impressora separado; Codex no PC ajusta impressora, evitar sobreposição.
- Ambiente: Python 3.12 (venv `/opt/pdv-venv` na nuvem), Qt offscreen, Tk requer Xvfb. Ficha código 31 pendente.
