# Handoff — 06/11/2026

## Show pelo código 33; número da garota só marca (pedido do usuário depois do PR #57)

- `quartos_codigo_show` (padrão 33; v43 preenche o campo vazio de bancos antigos) define o produto do show; o preço dele vira o valor do bloco (`QuartosController.config`).
- Número da garota na conta (`CaixaController.marcar_garota`, esquema v42: `vendas.garota_quarto/quarto_pedido`) não
  tem valor: liga a ela os shows já lançados e os próximos. Repetir o número não soma. `fechar` recusa show sem
  garota (`_conferir_shows_com_garota`). Sem código configurado, segue o produto QUARTO automático.

## Quarto automático pela comanda do cliente (branch nova, depois do merge do PR #56)

- `113` (número de garota cadastrada a partir de `quartos_garota_minimo`=100 vence produto; abaixo é produto), `113Q3` (quarto 3) ou `113Q`, no código do caixa, lança (G113 também vale); o produto do quarto (criado sozinho, `cfg quartos_produto`, preço =
  `quartos_valor_bloco`) ligado à garota; quantidade = blocos. Produto do quarto pelo código pergunta a garota.
- Ao pagar (`CaixaController.fechar` → `QuartosController.registrar_venda`): soma no quarto em que ela já está, ou
  inicia no pedido / livre há mais tempo, ou põe na fila (`quartos_vendas`, esquema v41). Shows pelo caminho de sempre
  (`_registrar_shows`). Tela avisa qual chave entregar (`_avisar_quartos`, lê do banco: `ctx.caixa` é novo a cada
  acesso). Liberar oferece a fila (`ui_qt/quartos.oferecer_fila`). Cancelar cupom desfaz (`desfazer_venda`).
- Decisões do usuário: cliente sempre paga antes; código da garota obrigatório.

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
- **Cadastro sem terminal:** a central gera o código de instalação `WILL1-` (endereço + loja + token) ao cadastrar e em
  "Gerar novo código de instalação"; "Gerar senha do painel do dono" substitui `backend.lojas painel`. No caixa, o
  botão da tela de entrada aceita o código: grava `api_url`, `chave_loja`, `api_token`, liga `painel_dono` e busca a
  licença (pergunta antes de trocar de loja).
- **Pacote de melhorias pedido pelo usuário (todas menos NFC-e):**
  - Aviso diário de licenças vencendo (`backend/avisos_fornecedor.py`, tabela `fornecedor_avisos`, e-mail para
    `PDV_AVISOS_EMAIL` ou `EMAIL_FROM`; gatilhos: varredura MP, abertura da central, consulta de licença do caixa).
  - Buscar fotos em lote (Cadastros > Produtos > Buscar fotos; thread + aprovação uma a uma).
  - Alterar quantidade da linha (`CaixaController.alterar_quantidade`, Ctrl+Q; diminuir = cancelamento parcial).
  - Promoção da gelada (esquema v38: `promo_gelada_cent`, `sem_gelada_cent`, `hora_gelada_cent`).
  - Kit de implantação e QR na central (`/lojas/{chave}/kit`; `segno` entrou no backend/requirements).
  - Prazo por fornecedor na reposição (esquema v39: `fornecedores.prazo_entrega_dias`; fornecedor habitual = última compra).
  - Cascos levados sem trazer viram empréstimo no cliente ao fechar (esquema v40: `itens_venda.cascos_emprestados`;
    regra decidida pelo usuário: anotar empréstimo, sem caução).
  - Combos com preço fixo (`ProdutoController.criar_combo`, botão Criar combo; regra do usuário: preço do combo fixo).
- Suíte completa local: 2474 testes OK (6 pulados), sem falha no encerramento do Qt; Node 9/9.

## Pendências

- **Antigravity (backend):** `backend/cardapio.py` ganhou edição pontual em `_url` para aceitar
  `data:image/jpeg;base64` até 12000 caracteres (miniatura da foto de arquivo). Publicar a nuvem para o cardápio mostrar
  essas fotos; sem isso, só as fotos vindas da internet aparecem.

- Conferir o CI do PR (build Windows gera `WillAdega-Setup-*.exe` e roda o autoteste procurando "Will Adega").
- Antes de vender: gerar o instalador pelo CI, instalar num Windows limpo, emitir licença `willadega` e fazer uma venda
  completa com leitor, impressora e gaveta (checklist em `docs/ADEGA.md`).
- Reposição: prazo por fornecedor e unidade de compra por produto ficaram de fora (exigem migração); decidir no piloto.
- **Central do fornecedor:** os achados da revisão do Claude foram corrigidos nesta branch: coluna `lojas.edicao` na
  nuvem (criada por `_acrescentar_colunas`), licença da nuvem sempre com o programa da loja (`assinar_ate` em
  `backend/licencas_fornecedor.py`), migração herda o programa do último código local, validade manual não reduz nem
  passa de 100 anos, consulta do caixa nunca cai por falta de chave ou corrida, login sem bloqueio geral. Publicar a
  nuvem depois do merge e marcar o programa das lojas Will Adega na central.
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
