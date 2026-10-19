# HANDOFF

## Último trabalho

**Decisão do titular:** a licença segue **manual** (WillPDV Licenças) e a nuvem serve **só para o painel do dono** (Render +
Neon, plano grátis). O trabalho do Asaas (worker e monitor no GitHub Actions, Render pago) não será usado: o PR #2 foi fechado
sem merge. O commit continua no histórico desta branch (`832bed9`) e o `cfa840f` o desfaz, caso a cobrança automática volte.

**Pedido:** concluir as três pendências do painel do dono. Guia completo em `docs/PAINEL_DONO.md`. As edições em `backend/`
(área do Antigravity) foram pontuais e pedidas pelo titular.

- **O dono troca a própria senha pelo PDV.** `painel_envio.trocar_senha_na_nuvem(url, token, senha)` chama
  `POST /v1/painel/senha` com o token da loja (em branco: a nuvem gera a senha e ela aparece uma vez). Tk: botão "Senha do
  painel do dono..." na barra de Configurações (grava antes o que está na tela; a rede roda numa thread, com janelinha de
  espera). Qt: botão na aba "Conexão com a nuvem" (QThreadPool; exige a aba salva; a janela não fecha com a troca em andamento).
  O log do PDV registra `painel_senha_trocada` (quem e se foi gerada, nunca a senha).
- **Mais de um caixa por loja.** Cada caixa se identifica (`painel_envio.id_do_caixa`: código gravado na config, que muda se o
  banco for copiado para outro computador) e a nuvem guarda **um retrato por caixa** (tabela nova `painel_caixas`; a antiga
  `painel_retratos` é apagada na subida, e o retrato se refaz em ~1 min). `GET /v1/painel/resumo` devolve `caixas[]` e mantém no
  topo `caixa`, `estoque`, `caderneta`, `entregas_pendentes` (turno aberto e estoque do primeiro caixa que tem; caderneta e
  entregas **somadas**), então o app antigo e o PDV antigo (sem `terminal_id`, entra como o caixa "unico") seguem funcionando.
  **Estoque não se soma** (cada caixa tem o seu banco): com mais de um caixa controlando, aparece um bloco por caixa. App do
  celular: um cartão por caixa na aba Caixa, de qual caixa saiu cada venda, "Sem enviar há ..." por caixa; `sw.js` foi para
  `painel-v2` e instala os arquivos com `cache: "reload"`.
- **Limpeza automática** (`backend/painel.py`: `limpar_antigos`, `limpeza_periodica`): vendas do painel com mais de 120 dias
  (`PDV_PAINEL_RETENCAO_DIAS`, mínimo 7; venda mais velha é confirmada ao PDV mas nem guardada), sessões vencidas e caixas sem
  retrato há 14 dias. Roda em segundo plano depois de um envio, no máximo a cada 6 h; `python -m backend.lojas limpar-painel`
  roda na hora. De quebra, o freio de tentativas de login deixou de crescer com nomes de loja inventados.

Testes novos: `test_painel_caixas`, `test_painel_limpeza`, `test_painel_senha_pdv` (regras e nuvem de verdade),
`test_painel_senha_tk` e 8 casos em `test_qt_configuracoes`. `test_painel_dono` ganhou a base `BaseNuvem` (relógio da nuvem fixo
em 2026-10-03, porque a retenção compara o dia da venda com a data do servidor). O job "Nuvem: testar e publicar" roda os que não
precisam de Tk/Qt.

### Validação

- Suíte completa (`xvfb-run`, `QT_QPA_PLATFORM=offscreen`, Python 3.12, Linux): **2179 testes, OK, 15 ignorados** pelo ambiente
  (nenhum é dos testes novos). Os testes do painel que falam com a nuvem (`test_painel_dono`, `_caixas`, `_limpeza` e
  `_senha_pdv`: 82, dos quais 57 novos) também passam contra **PostgreSQL 16 de verdade**
  (`PDV_TESTE_NUVEM_DB_URL=postgresql+psycopg://...`; atenção: o cluster precisa ser UTF8, em SQL_ASCII o psycopg devolve bytes),
  e a subida da versão nova sobre uma tabela `painel_retratos` antiga foi conferida lá. Os de tela (Tk e Qt) rodam só em SQLite. As sintaxes foram conferidas para o
  Python 3.10 do CI; o job da nuvem foi simulado num ambiente só com as dependências do `backend/`, sem Tk, Qt nem cryptography.
- Os testes foram conferidos com mutações (apagar a regra e ver o teste cair); os que sobreviveram foram reforçados.
- Ensaio real nesta sessão: API local (uvicorn + SQLite) com 3 PDVs enviando por HTTP de verdade; o app no Chromium (390x844,
  claro e escuro) com 3 caixas, com 1 e com a resposta antiga (sem `caixas`); troca de senha por HTTP real (escolhida, gerada,
  token errado, servidor fora do ar); janela do Tk numa tela virtual.
- **Não validado:** o app novo no Render/Neon, num celular de verdade e instalado como PWA; impressora e leitor; Windows.

## Pendências

- **Versão:** nada foi subido. Para levar a troca de senha e a identificação do caixa às lojas, subir `src/versao.py` e
  `instalador/WillPDV.iss` (sugestão 1.6.0) e gerar o instalador (workflow "Gerar instalador (Windows)" na `main`). O PDV novo
  funciona com a nuvem antiga; a nuvem nova funciona com o PDV antigo.
- **Nuvem no ar (Render + Neon, grátis):** o Neon está ligado e a `LOJA-TESTE` existe; falta homologar de ponta a ponta com um
  caixa enviando e um celular real. **Trocar o `PDV_API_TOKEN` e a senha do Neon** (apareceram numa conversa). Para o Render
  grátis não dormir: UptimeRobot em `GET /v1/saude` a cada 5 min (a rota é só GET: usar método GET ou palavra-chave; conferir se o
  plano grátis deles permite uso comercial).
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
