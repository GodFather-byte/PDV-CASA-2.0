# Handoff (18/11/2026): relatório do `rodar_testes` no Windows (branch `corrigir-rodar-testes-windows`)

Estado geral: repositório **público** (Actions de graça), build sem Nuitka, sem runner do PC. Última versão no `main`:
1.14.14 (não conferi se já foi publicada). A integração com o Insta-BDelivery (#124) está no `main`, **sem versão**.

## Este trabalho
- `tools/rodar_testes.py` quebrava no Windows com `UnicodeEncodeError` ao imprimir a saída de um módulo que falhou,
  quando ela trazia caractere fora do cp1252 (o `\ufffd` da decodificação, por exemplo). O job caía no `print` e a causa
  real da falha não aparecia no CI. Foi o que escondeu a falha de `test_autoteste` na primeira rodada do #124.
- Correção: `_saida_tolerante()` no começo do `main` reconfigura `stdout`/`stderr` com `errors="replace"`; o caractere
  que o terminal não escreve vira "?". Teste: `tests/test_rodar_testes.py` (saída em cp1252 estrito).

## O que entrou no #124 (já no `main`)
- **Segundo canal de pedido online: Insta-BDelivery** (vitrine de delivery com atendente de IA, outro repositório do
  dono: `GodFather-byte/Insta-BDelivery`). Ele fala o mesmo contrato do cardápio da nuvem (`/v1/cardapio/envio`,
  `/v1/pedidos-online`, `aceitar`, `recusar`, `situacao`), então o caixa só ganhou o endereço e a chave.
- **Dois canais convivem** (decisão do dono): a nuvem fica com o QR e o pedido da mesa; o Insta-BDelivery fica com
  entrega e retirada. Config: `instab_url` e `instab_token` (segredo), aba Conexão com a nuvem.
- `src/sync/insta_bdelivery.py`: endereço, chave e a regra do **`id` negativo**. Cada canal numera os seus pedidos, então
  o do Insta-BDelivery entra no caixa com `canal = "insta"` e `id = -numero`; é isso que vai em
  `vendas.pedido_online_id`. Sem coluna nova, sem migração (esquema segue v57).
- `src/sync/pedidos_online.py`: `fontes` (lida na thread da tela), `consultar_fontes` (só rede; um canal fora do ar não
  esconde o outro), `_destino` (id negativo vai para a vitrine). `ligado` = nuvem ou vitrine.
- `src/sync/cardapio_envio.py`: `enviar` publica na nuvem e depois na vitrine (`enviar_insta`, hash próprio em
  `instab_cardapio_hash`, que inclui endereço e chave); a falha de um destino não segura o outro. `sincronizador.py`
  **não foi tocado**: ele já chama `cardapio_envio.enviar`.
- `pedido_online_controller.marca(numero, canal)`: "Pedido Insta #N" x "Pedido online #N", para o #12 de um canal não
  casar com o do outro em `ja_importado`. `resumo` mostra "Insta #N".
- Testes: `test_insta_bdelivery` (13), `test_qt_insta_bdelivery` (2). Guia: `docs/INSTA_BDELIVERY.md`.
- Conferido de ponta a ponta com o Insta-BDelivery rodando localmente e os controladores reais do caixa: catálogo subiu,
  pedido virou entrega, aceito/saiu/entregue/recusado chegaram ao cliente, mudança de preço reenviou o catálogo.

## Pendências
- Merge deste PR (pedir OK do dono).
- **Decidir a versão** que leva o Insta-BDelivery às lojas. Não foi testado num caixa Windows instalado, nem contra a
  vitrine de produção com uma loja de verdade.
- Taxa de entrega: a vitrine passou a adotar `taxa_padrao_cent` e `minimo_cent` do envio do catálogo (mudança no
  repositório do Insta-BDelivery; cada valor só é aplicado quando muda no caixa). Conferido de ponta a ponta: total da
  vitrine igual ao do caixa com a taxa padrão. **Taxa por bairro continua divergindo**: a vitrine só tem a padrão e
  manda `bairro` vazio; o recado da entrega mostra o total que o cliente viu.
- Promoção por horário/data e preço gelado não aparecem na vitrine (ela usa o preço base).
- A aba Conexão com a nuvem não foi fotografada pelo `--telas` (a foto pega a primeira aba); os campos novos são
  desenhados pela lista `CAMPOS_CONFIG` como os demais.
- Herdadas: publicar 1.14.14 se ainda não saiu; loja com vários caixas no "apagar vendas de teste"; backlog NFC-e
  DeliciOz, IBS/CBS 2027, Casa Verde (1.14.5), mensalidade EA Superações.
