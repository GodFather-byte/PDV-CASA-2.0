# HANDOFF

## Último trabalho

**Véspera da entrega da adega** (o titular instala num cliente amanhã). Pedido: "falta algum módulo? se tiver, já faça".
Nuvem fica como está (painel do dono, commit `3fee76c`); hospedar no PC do cliente foi avaliado e descartado por ora.
Revisão feita olhando o primeiro dia de uma adega real; o que faltava era pequeno e foi fechado neste commit:

- **Cadastro rápido pelo leitor aceita preço gelada** (`ProdutoController.cadastrar_rapido(..., preco_gelada_cent=0)`):
  Tk ganhou o campo "Preço gelada (R$, opcional)" (última linha do diálogo, índices dos testes antigos preservados) e o
  Qt uma pergunta a mais, logo após o preço (fixtures de `test_adega_qt` ganharam a resposta extra).
- **Importação por planilha** aceita as colunas opcionais `Preço gelada`, `Atacado a partir de` e `Preço atacado`
  (vários nomes de cabeçalho; vazio não mexe, `0` desliga; faixa só com os dois campos e preço de atacado ≤ normal).
  Modelo e exportação levam as colunas; ida e volta testada.
- **Tabela de preços impressa** mostra, sob cada produto, o preço gelada e as faixas de atacado (natural e gelada).
- **Grade do caixa Tk**: etiqueta `[Natural]` só em bebida com dois preços; `[Gelada]`/`[Atacado]` quando valem; a
  observação não repete "Gelada" (no cupom continua inteira). `CaixaController.itens()` passou a trazer
  `preco_gelada_cent` do produto vivo (o histórico não tem a coluna).
- **Docs**: `docs/ADEGA.md` (checklist de implantação + treinamento do operador em 10 min), README (tabela de docs),
  `docs/ESTOQUE.md`, `docs/IMPORTAR_PRODUTOS.md`, `.ai/MAPA.md`. Versão **1.5.0** (`src/versao.py`, `WillPDV.iss`).

### Validação

- Suíte completa (`QT_QPA_PLATFORM=offscreen`, `python -m unittest discover -s tests`): **2104 testes, OK, 10 ignorados**
  (rodada antes do bump de versão; nada depende do número).
- Ensaio visual nesta máquina (script apagado): caixa Tk no perfil adega com atacado, gelada e casco lançados;
  diálogos de cadastro rápido (com o campo novo), temperatura e cascos; cupom impresso de uma venda com atacado,
  "* Gelada" e casco em linha própria. Capturas em `files/capturas/` da sessão, não no repositório.
- Não validado: leitor, impressora e gaveta físicos; instalador desta versão ainda não foi gerado (ver pendências).

## Pendências

- **Para a entrega de amanhã (titular):** `git push` para a `main` gera o instalador no GitHub (workflow
  "Gerar instalador (Windows)", release `ultima-versao`) e roda a suíte no CI; depois seguir `docs/ADEGA.md`.
  Levar o aviso por escrito do cupom NÃO FISCAL. Se quiser o painel do dono, a nuvem precisa estar no ar
  (`docs/NUVEM.md` + `docs/PAINEL_DONO.md`) e o segredo `RENDER_DEPLOY_HOOK_URL` é opcional.
- **Adega, evoluções não feitas:** cancelamento parcial de linha agrupada (hoje: Delete e relança `4*`); promoção por
  período só no preço natural (pergunta sem resposta); empréstimo/saldo de cascos por cliente; etiqueta de gôndola;
  várias faixas de atacado; atacado gelada pela planilha (só pela tela).
- **Painel do dono:** campo no PDV para o dono trocar a própria senha (rota `POST /v1/painel/senha` já existe); push;
  mais de um terminal por loja; limpeza de dados antigos; homologar no Render/Neon e num celular real.
- **Qt fora da adega:** alinhar pré-pago, rodízio/perfil, impressão por setor, dividir conta, balança, acerto das
  garotas e tipografia dos comprovantes. Não abrir Tk e Qt ao mesmo tempo sobre o mesmo banco.
- **Pré-pago:** confirmar a devolução em dinheiro de saldo recarregado no cartão; comprovante de recarga, RFID,
  relatório de recargas.
- Demais: split por item, rodízio por faixa, EAN de balança, consumação mínima por entrada, cobrança de comanda sem
  consumo; backup/restauração em outra máquina; Google Drive e senha do cofre do licenciador; cartões 184x126 e faixa 52
  na impressora real; regra de renovação a partir do vencimento (pede OK do titular); Asaas (homologar e hospedar
  API/worker supervisionados). Painel web do fornecedor (todas as lojas) e múltiplos caixas seguem fora de escopo.
