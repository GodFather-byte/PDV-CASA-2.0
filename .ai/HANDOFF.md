# Handoff (17/11/2026, 13h30): repositório PÚBLICO, sem Nuitka, sem runner do PC

- O dono mandou abrir o código (Actions de graça): o repositório está **público** desde 17/11. Antes, o histórico
  inteiro (438 commits, todas as branches) foi varrido: sem token, senha de banco, chave privada ou dado de cliente.
- Build sem Nuitka (`build_pdv.py --com-nuitka` é opcional); job "Compilar" e caches saíram dos workflows.
- O runner do PC (PC-WILLYANPHP) foi **excluído** do repositório (runner próprio em repositório público roda código de
  PR de fora no PC). A variável `RUNNER_PC` ficou, mas os workflows a ignoram em repositório público.
- `tools/rodar_testes.py`: suíte em paralelo por módulo, com limite e tempo de cada; o CI do Windows usa ele.
- Pendências: merge do PR #119 (XMLs na nuvem, teste grátis pelo site, IBS/CBS) e publicar 1.14.13.
- Gemini entrou na equipe para código pesado (17/11, ver AGENTS.md). Pendência: conferir os créditos de IA para gerar
  vídeo e música na conta Google do dono; não deu na sessão da nuvem (sem Claude in Chrome e sem computador conectado).

# Handoff (17/11/2026, tarde 2): XMLs na nuvem, teste grátis pelo site e IBS/CBS (branch `xml-nuvem-e-teste`)

- XMLs da NFC-e: emissão própria em produção avisa (`nfce_xmls.avisar`) e o sincronizador sobe em lotes de 20
  (gzip+Base64) para `POST /v1/nfce/xmls`; confirmados vão para `nfce_xmls_enviados` (esquema v56). A nuvem
  guarda por loja e mês (`nfce_xmls`), recusa DOCTYPE/ENTITY, nome estranho e gzip ruim. ZIP do mês:
  `/v1/painel/nfce/xmls?mes=` (dono) e `/v1/fornecedor/lojas/{chave}/nfce/xmls?mes=` (central, auditado).
- Teste grátis: formulário no site cria loja (chave `NOME-XXXX`), edição, licença até hoje+7, senha do painel e
  código de instalação. Limites: isca `site`, 3 por IP/dia, 1 por WhatsApp, teto diário `PDV_SITE_TESTES_DIA`
  (30); desliga com `PDV_SITE_TESTE=0`. A central mostra responsável/WhatsApp e botão para chamar quem não vende.
- IBS/CBS na emissão própria: grupo IBSCBS por item (CST 000 com valores; 400/410 sem) e IBSCBSTot, validados no
  XSD oficial. Regime normal manda sempre; Simples só ligado. Alíquotas configuráveis (padrão 2026).
- Corrigido teste antigo: `tests/test_ponte_pdv.TesteTelaQt` só fechava a janela e o Qt quebrava ao sair do
  processo (malloc_consolidate) quando o módulo rodava sozinho; agora apaga no teardown.
- Pendências: homologação DeliciOz (roteiro em docs/NFCE_PROPRIA.md); conferir alíquotas IBS/CBS de 2027.

# Handoff (17/11/2026, tarde): lojas em teste, implantação, E2E, build único e NFC-e (branch `central-teste`)

- Central: `listar` marca `em_teste` (ativa, licença valendo, nunca pagou pelo Mercado Pago, criada há até 60 dias)
  e `teste_parado` (sem venda fechada há 3+ dias ou nunca), com `uso` (vendas_7d, ultima_venda; só contagem).
  Indicador "Em teste", filtros e aviso no quadro de atenção.
- Implantação: depois de enviar planilha/catálogo, a retaguarda oferece lançar o serviço da tabela de preços cujo
  nome tem "implanta" ou "cadastr" (por unidade multiplica pelos itens). Central mostra "Serviços a receber"
  (`GET /v1/fornecedor/servicos/a-receber`).
- `tests/test_e2e_caixa.py`: caixa só no teclado (turno, bipar, pagar com troco, fechar) e está na fumaça do
  `tools/verificar`.
- Build: job "Compilar o código" no `build-windows.yml` compila o Nuitka uma vez e guarda `build/nuitka` no cache
  (chave = hash de src/**/*.py + compilar_nuitka + requirements); WillPDV e Adega `needs: compilar` e só restauram;
  Restaurante usa o mesmo cache (`actions/cache`). `compilar_nuitka.compilar()` reaproveita se `build/nuitka/chave.txt`
  bater. Era ~94 min de Windows por versão.
- NFC-e própria: contingência off-line automática (status sem resposta antes do 1º envio; QR v3 assinado RSA-SHA1;
  DANFE "EMITIDA EM CONTINGÊNCIA"; transmite o mesmo XML depois), inutilização (nota rejeitada ou faixa),
  botão "Testar SEFAZ". Esquema v55. Roteiro da homologação em `docs/NFCE_PROPRIA.md`.
- Pendências: homologação real na DeliciOz (precisa do A1 na loja: seguir o roteiro); XMLs na nuvem; IBS/CBS.

# Handoff (17/11/2026, 08h): verificação (branch `verificacao`)

- `python -m tools.verificar`: fumaça do caixa (test_caixa, propriedades, troca de forma, recebimento direto) +
  testes que importam o que mudou + `node --check`; `--telas` fotografa; imprime `Verificado: ...` para o commit.
- Skill `.claude/skills/verify/SKILL.md` (como verificar e quando parar), `REVIEW.md` na raiz (regras + lista por
  gatilho tirada de bugs reais; ler sempre o da main).
- `tests/test_propriedades_dinheiro.py`: vendas sorteadas com semente fixa (pago − troco = total, estoque baixa o
  vendido, cancelar devolve tudo, dividir soma o que falta, centavos ida e volta). Sem dependência nova;
  `WILLPDV_CASOS=500` para sortear mais. Com 600 casos não achou furo.

# Handoff (17/11/2026, manhã): 1.14.11, serviços do fornecedor e estoque no resumo (branch `melhorias-vendas`)

- Combos e atacado já existiam (`produto_controller.criar_combo`, campos `atacado_qtd`/`preco_atacado_cent`); não mexi.
- Central > retaguarda da loja > Serviços cobrados: tabela de preços global (`retaguarda_precos_servico`, "por unidade"
  multiplica pela quantidade), lançar, "Cobrar no Pix" (Mercado Pago, `external_reference = servico-<id>`, pagador =
  e-mail do plano da loja; abre o WhatsApp do plano com o texto e o copia e cola), "Conferir pagamento" e baixa
  automática pelo webhook (`cobranca_mercadopago.aplicar` desvia `servico-*` para `retaguarda.aplicar_pagamento_servico`).
  Colunas pix_* entram por `retaguarda.garantir_colunas` (a tabela nasceu sem elas no deploy do #113).
- Importar planilha (central): botão "Carregar catálogo da adega", filtro por grupo; só vão as linhas com preço. O lote
  aceita `ncm`, `preco_gelada`, `atacado_qtd`, `preco_atacado`; o caixa preenche o NCM de quem ainda não tem.
- Resumo da noite (WhatsApp) ganhou "Acabando (comprar)" (`estoque_controller.acabando`); o painel do dono mostra
  "Parados há 30 dias" com o valor parado (`estoque_controller.parados`, enviado em `estoque.parados`).
- Versão 1.14.11. Publicar WillPDV e Will Adega e manter `PDV_ATUALIZACAO_PAUSADA=0` (todas as lojas).

# Handoff (17/11/2026): adega e serviço de cadastro em massa (branch `vendas-adega`)

- Importar produtos (caixa): na prévia, Preço e Estoque são editáveis (duplo clique ou digitar); vazio fica laranja e
  a análise refaz a cada célula (`ui_qt/importar_produtos.py`, `_celula_editada`). A janela de NF-e não mudou.
- Catálogo da adega com 274 itens: tabacaria completa (essências, sedas, piteiras, isqueiros, alumínio, carvão, fumo),
  mais energéticos, refrigerantes, ices e águas. NCMs novos em `fiscal/ncm.py`.
- Serviço do fornecedor (cobrado à parte), só pela central (`/retaguarda/?loja=CHAVE`):
  - "Importar planilha de produtos": a nuvem lê CSV/XLSX (`POST .../retaguarda/planilha`, mesmas regras de
    `ler_tabela_dados`), o fornecedor corrige preços na tela e envia em lotes de 200 como comando `produtos.importar`.
    O dono não pode mandar esse tipo (403). O caixa aplica com `ImportacaoProdutos` numa transação e devolve
    "N criado(s), N atualizado(s); N recusado(s): motivos" no detalhe do comando.
  - "Serviços cobrados": tabela `retaguarda_servicos` (descrição, valor_cent, pago_em), lançar e marcar "Recebi".
    Cada lançamento entra na auditoria da central. Ainda não gera cobrança no Mercado Pago (próximo passo possível).
  - Caixa antigo recusa `produtos.importar` ("Atualize o programa da loja"): precisa da próxima versão.
- Pendências: publicar a versão com isso; ideias de caixa (tarefa #28) aguardando o dono escolher.

# Handoff (16/11/2026, noite): 1.14.10, recebimento direto na adega

- Pedido do dono: receber na adega estava complicado (Enter, forma, Enter, valor, Enter, Enter) e a taxa de R$ 5,00 do
  crédito é só da boate.
- `pagamento_direto` (Configurações > Caixa, padrão N): Enter com o código vazio (ou F12) vai direto ao valor já
  preenchido em Dinheiro; Enter recebe e, com a conta paga, a venda fecha sozinha. No campo do valor a letra (D, C, P) ou
  as setas trocam a forma. Parcial: fica no valor com o que falta. Código em `ui_qt/caixa.py` (`ir_para_pagamento`,
  `_tecla_valor`, `receber`, `_falta_receber_no_direto`). Teste: `tests/test_qt_pagamento_direto.py`.
- Will Adega, uma vez por banco (`edicao.preparar`, marca `adega_recebimento_simples`): zera acréscimo de 500 nas formas
  e liga `pagamento_direto`. Depois o dono manda. WillPDV e Restaurante não mudam. Teste em `tests/test_edicao.py`.
- Com o recebimento direto a venda fecha ao pagar, então a troca de forma do #104 só vale no fluxo clássico.
- 1.14.10 publicada em 16/11 (WillPDV e Will Adega, pacote assinado). Em 17/11 o dono mandou liberar para todas as
  lojas: `PDV_ATUALIZACAO_PAUSADA=0` no Render (willpdv-nuvem); `PDV_ATUALIZACAO_PILOTO` ficou como estava. Para segurar
  de novo, volte a pausa para 1. Will Restaurante tem build próprio (`will-restaurante.yml`) e não saiu nesta versão.

# Handoff (16/11/2026)

- Testes de volta no GitHub (PC do dono com problema): o workflow lê `vars.RUNNER_PC` (não existe), a antiga
  `RUNNER_WINDOWS` ficou ignorada. Economia em `testes.yml`: PR = Linux inteiro + 2 curtos de Windows + PostgreSQL;
  merge = só Windows 3.12 inteiro; docs/.ai/*.md não rodam; push novo no PR cancela a rodada anterior.
- Publicação usa rascunho (Release draft) no willpdv-downloads (#109), não depende da cota de artifacts.
- 1.14.9 publicada (piloto CASA-VERDE). Casa Verde ainda informa 1.14.5: instalar na mão uma vez.

# Handoff — código privado e compilado com Nuitka (14/11/2026)

## 15/11 (tarde)

- #104 caixa: com a conta paga, escolher outra forma pergunta e troca o último pagamento (`_trocar_forma_paga`).
- #105 nuvem: caixa da ponte de loja fora do modo ponte recebe a licença da nuvem (Casa Verde ficava 404 a cada hora).
- #106 teste Windows: limpeza espera o .exe ser solto (falha intermitente da Publicação assinada).
- #107 tema novo (botões centralizados com hierarquia automática primário/perigo, Fechar sozinho
  à direita, tabelas com colunas ajustadas e linhas de 28 px, barras de rolagem finas, abas, campos, menus, dicas) e
  `tools/capturar_telas.py` (`QT_QPA_PLATFORM` offscreen com monitor fictício 1366x768) para revisar tudo de uma vez.
- 1.14.9 publicada em 15/11 com tudo isso (piloto: só CASA-VERDE). Nuvem: deploy automático do Render não dispara
  depois da troca de conexão; usar Manual Deploy ou o secret RENDER_DEPLOY_HOOK_URL (nuvem-deploy.yml).

## Agora (branch `nuitka`)

- Repositório PDV-CASA-2.0 está PRIVADO (14/11). Instaladores e pacotes no público `willpdv-downloads`. O Render
  passou a usar a conexão GitHub (credencial willyan-neres) em 15/11; deploy do #102 no ar.
- 1.14.9 = primeira versão compilada (Nuitka). Piloto continua só CASA-VERDE.
- Nuitka: `tools/compilar_nuitka.py` compila cada pacote de `src/` (`--mode=package`, um `.pyd` por pacote) e o
  `build_pdv.py` (`argumentos_codigo`) entrega ao PyInstaller as extensões com `--exclude-module src.<pacote>`,
  `--add-binary` e os imports de fora como `--hidden-import`. Só app/autoteste/versao/homologacao ficam em Python.
  `--sem-nuitka` só em emergência. `atualizacao/` e `cardapio/` ganharam `__init__.py`. Teste: `tests/test_nuitka_build.py`.
- Conferido no Linux: compilação (12 min, 2 núcleos), PyInstaller, `--autoteste` e `--autoteste-qt` TUDO CERTO, e só
  5 módulos `src` no PYZ. No Windows (workflow na branch): WillPDV e Adega geraram, autoteste do .exe e do instalado
  OK; build ~34 min por edição (Nuitka quase tudo). #102 na main.
- Suíte rodando contra o código compilado: o que falha é teste que troca `sys.platform` (o Nuitka fixa a constante),
  não o programa.
- Timeouts dos builds: 60 min (WillPDV, Adega), 50 (Restaurante). Ideia de economia: compilar uma vez e reaproveitar
  entre as edições (artifact).

## Antes (versão 1.14.8: emissão própria da NFC-e, #99)

- Emissão própria da NFC-e direto na SEFAZ-SP (decisão do dono: cobrar adicional menor e ganhar no volume). Guia em
  `docs/NFCE_PROPRIA.md`. Código em `src/fiscal/sefaz/` (chave, xml_nfce, assinatura, qrcode, cliente, provedor);
  provedor escolhido por `nfce_provedor` (focus | propria) em `FiscalController.transmissor()`; a fila não mudou.
- Testes: `tests/test_nfce_sefaz.py` valida o XML nos schemas oficiais (PL_010 v1.30, em `tests/dados/xsd_nfe/`,
  baixados de nfephp-org/sped-nfe), confere a assinatura e simula a SEFAZ (autoriza, rejeita, resposta perdida,
  cancelamento). Nova dependência: `lxml` (requirements.in/.txt regenerados com uv).
- Ainda não falou com a SEFAZ de verdade. Piloto: DELICIOZ (Osasco, Simples, A1 da própria loja), instalação marcada
  para 15/11; o dono levanta credenciamento NFC-e, IE, série/último número e CFOP/CSOSN com o contador. Primeiro teste: status do
  serviço em homologação; se der SSLError, embutir a cadeia ICP-Brasil.
- Falta: contingência off-line (QR v3 assinado; confirmar no Manual DANFE NFC-e v6), inutilização, XMLs na nuvem,
  IBS/CBS na emissão própria.
- Outras pendências: Casa Verde instalar a 1.14.7 (piloto `CASA-VERDE` no Render; 1.14.7 publicada); depois liberar
  as outras lojas; mensalidade da rede EA.

---


Branch `rede-app-e-mensalidade`, criada da main depois do #91. Pedido do dono: PWA para a rede EA Superações
(cliente com 4 lojas) e juntar as assinaturas das lojas numa só ("depois eu coloco o valor"). Guia: `docs/REDE_LOJAS.md`.

## O que já existia

Rede (`backend/grupos.py`): login único no painel, central da rede, volta para a lista, e a mensalidade única
(`definir_assinatura`, que renova todas as lojas ao pagar e para as cobranças próprias delas), mas esta só pela API admin.

## O que foi feito

- `GET /painel/rede.webmanifest?grupo=CHAVE` (`backend/painel.py`, `grupos.manifesto`): o app instalado tem o nome da
  rede e abre no login dela. Rede desconhecida recebe o manifesto comum.
- Painel (`painel_web/app.js`): `aplicarAppDaRede` troca o manifesto, o título e o nome do iPhone quando há rede
  (link ?grupo=, sessão da rede guardada ou depois de entrar). Quadro "Ter o app da rede no celular" na tela da rede, com
  botão "Instalar agora" no Android. Service worker `painel-v15`.
- Central (`central_web/app.js` + `POST /v1/fornecedor/grupos/{chave}/plano`): formulário "Mensalidade da rede" em cada
  rede, preenchido com o plano atual (`grupos.plano` entra no `resumo`), com motivo na auditoria.
- Testes em `tests/test_grupos_rede.py`.

## Para o dono fazer (EA Superações)

1. Central > Redes: criar a rede (se ainda não existe) e incluir as 4 lojas.
2. Na rede: "Mensalidade da rede" com o valor, o dia e os dados do pagador. Salvar.
3. Mandar ao cliente o link `https://<nuvem>/painel/?grupo=CHAVE` e a senha temporária; ele instala pelo quadro
   "Ter o app da rede no celular".

## Pendências

- Proteger o código: `docs/PROTEGER_CODIGO.md`. Feito: repositório de downloads com token e variável, publicação lá
  conferida. Falta: conferir as variáveis `PDV_INSTALADOR_*` no Render e como o Render puxa o código (conector do Render
  não está ligado), runner no PC, mudar para privado. Depois: Nuitka.
- Tutoriais: próximos no caixa de treino (fechar caixa, desconto, cancelar item) em `ui_qt/treino.py`.
- Empório: conta Focus, certificado e CSC no painel da Focus, token de homologação (`docs/NFCE.md`).
- Pix integrado: testar com o Mercado Pago real (Pix de R$ 0,01), `docs/PIX.md`.
- Atualização sem UAC (#85): teste em PC real pendente; pausa retirada em 17/11 (acompanhar as lojas).
