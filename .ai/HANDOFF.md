# HANDOFF

## Último trabalho

**Painel do dono no celular** (PWA), pedido logo depois da modernização da adega (commit `9bf8cdb`, que
continua descrita em `docs/ESTOQUE.md` e no HANDOFF anterior no git). O titular perguntou se dava para o
dono acompanhar tudo pelo celular "rodando pelo GitHub Actions"; a resposta foi: sim ao app instalável
pelo navegador, Actions só testa e publica (não hospeda). Ele mandou fazer. Decisões tomadas sem resposta
dele (titular ausente): envio **opcional e desligado por padrão**; senha do dono separada do token do PDV,
definida pelo fornecedor; PWA servida pela própria API; deploy pelo Deploy Hook do Render.

### Entregue (commit deste HANDOFF)

- **PDV** `src/sync/painel_envio.py` (novo): a cada rodada do `--sync`, com `painel_dono = S`, sobe as vendas
  fechadas/canceladas com `sincronizado = 0` (itens com temperatura/preço-base, pagamentos, dia operacional
  pela virada) em lotes de 200 e um retrato (turno via `TurnoController.resumo`, estoque zerado/abaixo do
  mínimo, caderneta a receber, entregas pendentes). Só marca `sincronizado = 1` nos uuids que a nuvem
  confirmou; cancelar venda já zera a marca (código existente), então o cancelamento sobe de novo.
  `sincronizador.rodada` chama `_enviar_painel` (edição pontual no arquivo do Antigravity).
  Config nova `painel_dono` (sementes + aba Nuvem do `CAMPOS_CONFIG`). Registrado em `autoteste.MODULOS`.
- **Nuvem** `backend/painel.py` (novo), instalado no fim de `backend/main.py` com `instalar(app, Loja, autenticar)`
  (sem import circular). Tabelas `painel_acessos` (PBKDF2 da senha), `painel_sessoes` (30 dias, hash do token),
  `painel_vendas` (único por loja+uuid, venda inteira em JSON, agregação em Python na consulta),
  `painel_retratos`. Rotas: `POST /v1/painel/envio` (token da loja), `POST /v1/painel/senha` (token da loja),
  `POST /v1/admin/lojas/{chave}/painel` (admin; gera senha xxxx-xxxx-xxxx se não informar),
  `POST /v1/painel/login` (8 erros/15 min bloqueiam, em memória), `/sair`, `GET /resumo?dia`, `/vendas?dia&pagina`,
  `/historico?dias`. `/painel/` serve a PWA (`FileResponse` no index + `StaticFiles`). CLI
  `python -m backend.lojas painel LOJA [senha]` (edição pontual em `lojas.py`).
- **PWA** `backend/painel_web/` (agente): index/app.js/estilo.css/sw.js/manifest, 4 abas (Hoje, Caixa, Produtos,
  Vendas), vanilla, offline com último resumo em localStorage, SW cache-first só do shell (nunca `/v1/`).
  Ícones PNG gerados por `tools/gerar_icones_painel.py` (sem Pillow).
- **Actions** `.github/workflows/nuvem-deploy.yml`: testa (`test_painel_dono`, `test_nuvem`, manifesto) e, em
  push na `main` com o segredo `RENDER_DEPLOY_HOOK_URL`, chama o hook. Sem segredo só testa.
- **Docs**: `docs/PAINEL_DONO.md` (novo, guia completo), `docs/NUVEM.md` (tabela inicial, aba Nuvem, seção 7),
  `.ai/MAPA.md`. `tests/test_nuvem.py`: o teste "não tem painel" virou "não tem envio genérico nem painel do admin".

### Validação

- `tests/test_painel_dono.py` (25 casos: envio, lotes, marcação parcial, cancelamento reenviado, retrato, laço do
  sincronizador; nuvem: envio/upsert, senha/sessão/bloqueio/isolamento entre lojas, resumo com atacado e
  gelada, paginação, histórico, PWA servida, CLI). Rodado junto com `test_nuvem`, `test_autoteste`,
  `test_modulos`, `test_perfil`, `test_qt_configuracoes`, `test_atualizacoes`, `test_licenca_nuvem`: **134 OK**.
- Ensaio de ponta a ponta nesta máquina: uvicorn local + SQLite + PDV de teste enviando 5 vendas via `requests`;
  painel aberto no navegador (390 px): login, 4 abas e valores conferidos à mão (Pix 82,18; esperado na gaveta
  123,00; economia do atacado 6,12). Script do ensaio foi apagado (não ficou no repositório).
- Suíte completa **não** foi rodada de novo depois deste trabalho (a última completa foi antes do commit da adega,
  2070 testes, 1 falha corrigida). O CI roda tudo no push.
- Para os testes da nuvem rodarem localmente: `python -m pip install -r backend/requirements.txt httpx requests`
  (foram instalados nesta máquina durante a sessão).

## Pendências

- **Titular decide**: (1) ligar o painel para quais lojas e definir as senhas (`backend.lojas painel`); (2) cadastrar
  `RENDER_DEPLOY_HOOK_URL` nos segredos do GitHub se quiser deploy automático; (3) a promoção antiga vale só para
  o preço natural (pergunta sem resposta na sessão da adega).
- **Painel, evoluções não feitas**: campo no PDV para o dono definir a própria senha do painel (a rota
  `POST /v1/painel/senha` já existe; falta a tela em Configurações > Nuvem, Tk e Qt); avisos push; mais de um
  terminal por loja (o retrato é do último que enviou); apagar dados antigos da nuvem; freio de login persistente
  (hoje em memória por processo); homologar no Render + Neon de verdade e num celular real (Android/iPhone: instalar,
  offline, dark mode). Nada disso foi testado fora desta máquina.
- **Adega** (do commit anterior): homologar com leitor/impressora/gaveta reais; NFC-e continua fora (cupom NÃO
  FISCAL); retornáveis avançados, etiquetas de gôndola e várias faixas de atacado ficaram fora.
- **Qt fora da adega**: alinhar com o Tk pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança,
  acerto das garotas e tipografia dos comprovantes. Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco.
- **Pré-pago**: confirmar a devolução em dinheiro de saldo recarregado no cartão; comprovante de recarga, RFID,
  relatório de recargas.
- Demais: split por item, rodízio por faixa, EAN de balança, consumação mínima por entrada, cobrança de comanda
  sem consumo; backup/restauração em outra máquina; Google Drive e senha do cofre do licenciador; cartões
  184x126 e faixa 52 na impressora real; regra de renovação a partir do vencimento (pede OK do titular); Asaas
  (homologar credenciais/webhook e hospedar API/worker supervisionados). Painel web do **fornecedor** (todas as
  lojas) e múltiplos caixas seguem fora de escopo.
