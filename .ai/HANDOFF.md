# Handoff de 25/11/2026: produto novo com custo e base de produtos (branch `cadastro-rapido-custo`)

- `src/ui_qt/produto_novo.py` (`DialogoProdutoNovo`) troca a sequência de perguntas do cadastro rápido por uma tela
  só, com o preço de custo (só para nível 4 ou mais). Os testes roteirizam pelo `Dialogos.produto_novo`.
- `ProdutoController.cadastrar_rapido` passou a aceitar `custo_cent` e `ncm`.
- `src/controllers/base_codigos.py` lê `src/dados/base_codigos.csv` (o `build_pdv.py` copia para `dados/` no
  executável). O caixa procura nela antes da internet. A ferramenta é `tools/base_codigos.py` (juntar/conferir/
  modelo). A base sai vazia: falta a lista do dono, a ser conferida pela ferramenta.
- Testes: `tests/test_base_codigos.py`.

# Handoff de 24/11/2026: caixa adicional se atualiza junto (branch `adicional-atualiza`)

- `rede.ErroVersaoDiferente`: o principal recusa por versão e manda `versao_principal`, `nuvem` (sem token) e `loja`
  (`ServidorBanco._dados_da_versao`).
- `src/atualizacao/adicional.py`: `pode_atualizar`, `atualizar` (consulta, confere, baixa e dispara a tarefa; aceita
  só a mesma versão; uma tentativa a cada 30 min) e `esquecer_tentativa`.
- Telas: `rede_caixas.atualizar_adicional` (espera com a tela viva). `app.main` atualiza na abertura.
  `App._vigiar_principal` roda a cada 60 s só no adicional, e `_atualizar_adicional_em_uso` só pergunta se houver
  operador logado.
- Teste: `tests/test_atualizacao_adicional.py`. Documentação: `docs/ATUALIZACAO.md`, "Caixa adicional".

# Handoff de 24/11/2026: foto e código de barras na retaguarda (branch `retaguarda-barras-foto`, em cima do #162)

- Nuvem: `GET .../retaguarda/codigo-barras/{gtin}` (`consultar_gtin`) consulta o Open Food Facts e devolve o nome e
  a miniatura como data URL, porque a página só aceita imagem do próprio site. Fica 12 h em cache e não grava nada.
  Comando novo: `produto.foto` (`origem`: `codigo_barras`, `arquivo` com `imagem_b64` até 56 KB, ou `remover`). O
  produto vai por `produto_id` ou, se foi recém-cadastrado, por `codigo`. Filtro `sem_foto`.
- Caixa: `RetaguardaController._foto_produto` usa `foto_produto_controller` (as mesmas regras e limpeza da foto do
  caixa). O espelho de produtos ganhou a coluna `tem_foto`.
- Tela: bloco "Foto e código de barras" na ficha do produto. A foto do celular é reduzida no próprio navegador
  (canvas). Teste: `tests/test_retaguarda_foto.py`.

# Handoff de 24/11/2026: hotel só hotel, papéis das garotas, mostrar senha e retaguarda (PRs #160, #161, #162)

- **#160 Will Hotel** (`hotel-so-hotel`): `Edicao.inicio = "hotel"` faz a recepção abrir sozinha depois da entrada
  (também para o operador só de caixa). `Edicao.rotulos` troca os textos do menu, e `menu_oculto` esconde o que é de
  boate e adega. O caixa continua para turno, sangria e receber a conta. Teste: `tests/test_qt_hotel_inicio.py`.
- **#161 Garotas** (`garotas-reimprimir`): `ComissaoController.acertos`, `lancamentos_periodo` e `recibo_do_acerto`
  remontam o pagamento a partir do banco. `ImpressaoController.reimpressao_recibo_garota` e `reimpressao_via_comissao`
  geram a segunda via com a marca. No caixa: `DialogoReimpressao`, aberto pelo botão "Reimprimir papéis" em Comissões.
  O retrato do painel leva `comissoes.acertos` e `consumo_pendente_cent`, e o painel ganhou a aba **Garotas**
  (`aba-garotas`; o bloco de comissões saiu do Salão). Testes: `test_qt_reimpressao_garota.py` e
  `test_painel_garotas.py`.
- **#162 Painel e retaguarda** (`painel-senha-retaguarda`): `configurarMostrarSenha()` no painel. Na retaguarda,
  `cadastro()` aceita `filtro` (`FILTROS_PRODUTO`), `ordem`/`desc` e `todas` (exportação). A tela ganhou filtro,
  ordenação no título da coluna, "Exportar planilha" (CSV) e "Duplicar". Teste: `tests/test_retaguarda_filtros.py`.
- Os três precisam de nova versão do caixa (1.14.24). O painel e a retaguarda entram com o deploy da nuvem. Os
  pagamentos das garotas só aparecem no painel depois que o caixa da casa atualizar.

## Antes: correções da auditoria (branch `cursor/correcoes-seguranca-e8a2`)

O dono aprovou os achados. Este trabalho só corrige; não publica nem faz merge.

- Backup da nuvem passa a ir cifrado (o mesmo AES-GCM do backup em pasta). A chave é o
  token da loja: a nuvem guarda só o cifrado. Backup antigo, em claro, ainda restaura.
  `POST /v1/fornecedor/lojas/{chave}/backups/apagar-abertos` apaga os antigos só se já
  existe um cifrado. Não roda sozinho.
- `/docs`, `/redoc` e `/openapi.json` só abrem com `PDV_ABRIR_DOCS=1`.
- O caixa não manda o token para HTTP público. HTTP fica em localhost, IP de rede local,
  nome `.local` e `testserver`.
- Central: a senha certa não conta tentativa e não fica presa. Trava de 2 minutos por IP.
  O `render.yaml` sobe o uvicorn com `--proxy-headers --forwarded-allow-ips=*`.
- Webhook do site sem `MP_WEBHOOK_SECRET` responde 503.
- Cabeçalhos de segurança em toda resposta. `X-Forwarded-Proto: http` em host público
  manda GET/HEAD para HTTPS (308) e recusa o resto (400).
- Porteiro: CORS sem `*`. PIN continua com limite por IP e ganhou limite por loja.
- Pillow 13 no Python 3.11+ (o caixa Windows é 3.12). O 3.10 fica no 12.3 porque o 13
  não instala nele.
- O navegador do painel usa cookie `HttpOnly` (`X-PDV-Painel: 1`). O assistente segue
  com o Bearer do login.

Precisa de versão nova do caixa para o backup cifrado e para recusar HTTP público.
Sem essa versão, a nuvem recusa backup em claro.

A API confere só o prefixo `WILLPDV-BKP`. Não importa a cifra: o job do PostgreSQL
não instala `cryptography`, e puxar esse módulo derrubava a subida da API nesse job.
`src.core.endereco_nuvem` está em `src/autoteste.py` (`MODULOS`).
