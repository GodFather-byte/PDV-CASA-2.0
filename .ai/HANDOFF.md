# HANDOFF

## Último trabalho

**Versão do PDV subida para 1.6.0** (pedido do titular): `src/versao.py` e o padrão de `instalador/WillPDV.iss` são os únicos
lugares onde o número existe (o `build_pdv.py` e a faixa da tela principal leem de `src/versao.py`). O instalador novo sai do
workflow "Gerar instalador (Windows)" quando isto chega na `main` (Releases > "última versão"). O WillPDV Licenças tem versão
própria (1.1.0) e não mudou.

**O que a 1.6.0 traz** (PRs já mesclados na `main`; guia completo em `docs/PAINEL_DONO.md`):

- **O dono troca a própria senha do painel pelo PDV:** Configurações > botão "Senha do painel do dono..." (Tk) ou aba "Conexão
  com a nuvem" (Qt). Usa `POST /v1/painel/senha` com o token da loja; em branco, a nuvem gera a senha e ela aparece uma vez.
- **Vários caixas por loja:** cada caixa se identifica (`painel_envio.id_do_caixa`) e a nuvem guarda um retrato por caixa
  (`painel_caixas`). Caderneta e entregas somam; o estoque **não** (cada caixa tem o seu banco). Só passa a valer para as lojas
  quando **todos** os caixas estiverem na 1.6.0: PDV mais antigo entra na nuvem como um caixa só ("unico").
- **Limpeza automática na nuvem:** vendas do painel com mais de 120 dias (`PDV_PAINEL_RETENCAO_DIAS`), sessões vencidas e caixas
  parados há 14 dias saem sozinhos; `python -m backend.lojas limpar-painel` roda na hora. É só da nuvem (não depende da versão
  do PDV). O histórico completo continua no caixa.
- PDV novo funciona com a nuvem antiga e a nuvem nova funciona com o PDV antigo.

**Decisão do titular:** a licença segue **manual** e a nuvem serve **só para o painel do dono** (Render + Neon, plano grátis).
O trabalho do Asaas (worker e monitor no GitHub Actions, Render pago) não será usado: o PR #2 foi fechado sem merge. O commit
continua no histórico (`832bed9`) e o `cfa840f` o desfaz, caso a cobrança automática volte. As edições em `backend/` (área do
Antigravity) foram pontuais e pedidas pelo titular.

### Validação

- Suíte completa antes da subida de versão (`xvfb-run`, `QT_QPA_PLATFORM=offscreen`, Python 3.12, Linux): **2179 testes, OK, 15
  ignorados** pelo ambiente; Windows e Linux, Python 3.10 e 3.12, passaram no GitHub. Os testes do painel que falam com a nuvem
  também passam contra PostgreSQL 16 de verdade (`PDV_TESTE_NUVEM_DB_URL=postgresql+psycopg://...`; o cluster precisa ser UTF8).
- Ensaio real: API local com 3 PDVs enviando por HTTP, o app do celular no Chromium (claro e escuro; 3 caixas, 1 caixa e a
  resposta antiga) e a troca de senha por HTTP real.
- **Não validado:** o app novo no Render/Neon, num celular de verdade e instalado como PWA; impressora e leitor; Windows na prática.

## Pendências

- **Publicar a 1.6.0 na nuvem** para os caixas conectados avisarem o dono (ação do titular, precisa do banco do Neon; exemplo):
  `python -m backend.atualizacoes publicar 1.6.0 --notas "Painel do dono: o dono troca a senha do painel em Configurações; lojas com mais de um caixa aparecem separadas no celular." --url https://github.com/GodFather-byte/PDV-CASA-2.0/releases/tag/ultima-versao`
  (trocar a `--url` se o repositório ficar privado ou se o instalador for entregue de outro jeito). Release versionada com o
  instalador `WillPDV-Setup-1.6.0.exe` é por tag (`git tag v1.6.0 && git push origin v1.6.0`, ver `docs/INSTALAR_E_TESTAR.md`): não foi criada.
- **Nuvem no ar (Render + Neon, grátis):** o Neon está ligado e a `LOJA-TESTE` existe; falta homologar de ponta a ponta com um
  caixa enviando e um celular real. O GitHub não aciona o deploy (falta o segredo `RENDER_DEPLOY_HOOK_URL`): conferir no Render
  se o Auto-Deploy está ligado. **Trocar o `PDV_API_TOKEN` e a senha do Neon** (apareceram numa conversa). Para o Render grátis
  não dormir: UptimeRobot em `GET /v1/saude` a cada 5 min (a rota é só GET: usar método GET ou palavra-chave; conferir se o plano
  grátis deles permite uso comercial).
- **Ao ligar o painel em loja com meses de histórico:** todo o histórico ainda não enviado sobe (lotes de 200, de uma vez) e a
  nuvem descarta o que passa de 120 dias. Se pesar, o PDV pode deixar de mandar vendas mais velhas que a retenção (não feito).
- **Painel:** campo para o dono trocar a senha também no próprio app do celular (hoje só pelo PDV ou pelo fornecedor); push;
  homologar a instalação como PWA no Android e no iPhone.
- **Estoque com dois caixas** é por caixa, por desenho. Um estoque único exige vários caixas no mesmo banco (fora de escopo, ver
  `docs/ESPECIFICACAO.md`).
- **Adega, evoluções não feitas:** cancelamento parcial de linha agrupada (hoje: Delete e relança `4*`); promoção por período só
  no preço natural; empréstimo/saldo de cascos por cliente; etiqueta de gôndola; várias faixas de atacado; atacado gelada pela
  planilha (só pela tela). Entrega da adega: `docs/ADEGA.md` e o aviso por escrito do cupom NÃO FISCAL.
- **Qt fora da adega:** alinhar pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança, acerto das garotas e
  tipografia dos comprovantes. Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco.
- **Pré-pago:** confirmar a devolução em dinheiro de saldo recarregado no cartão; comprovante de recarga, RFID, relatório de
  recargas.
- **Demais:** split por item, rodízio por faixa, EAN de balança, consumação mínima por entrada, cobrança de comanda sem consumo;
  backup/restauração em outra máquina; Google Drive e senha do cofre do licenciador; cartões 184x126 e faixa 52 na impressora real;
  regra de renovação a partir do vencimento (pede OK do titular); cobrança Asaas só se voltar (o que existe: `backend/cobrancas.py`,
  `operacao_asaas.py`, `worker_asaas.py` e o commit `832bed9`). Painel web do fornecedor (todas as lojas) e vários caixas no mesmo
  banco seguem fora de escopo.
