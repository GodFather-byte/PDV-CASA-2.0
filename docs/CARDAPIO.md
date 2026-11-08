# Cardápio digital (QR da mesa)

Página pública, só consulta, no celular: `https://nuvem.exemplo/cardapio/?loja=CHAVE&mesa=4`.
Não faz pedido, não mostra custo, estoque, produto inativo, fora de venda ou com **Mostrar no cardápio digital** desmarcado.

O preço é o vigente do caixa (promoção por período, dia da semana ou happy hour — vale o menor). A nuvem recalcula na hora da abertura, no horário de Brasília, para o happy hour não ficar preso na hora do envio.

## O que o caixa envia

Com **Configurações > Nuvem > Cardápio digital** ligado (e endereço + token preenchidos), cada rodada da sincronização publica o catálogo. Reenviar substitui o anterior. Se nada mudou, não chama a nuvem. Desligar a opção tira o cardápio do ar na próxima rodada.

Sobe: nome, grupo, subgrupo, preço e as regras de promoção, o texto de sugestão do produto (se houver) e, no subgrupo, um endereço `http`/`https` de foto. O logotipo da loja sobe como miniatura, se o arquivo existir. Não sobe arquivo local de foto, custo nem quantidade em estoque.

No cadastro do produto, **Mostrar no cardápio digital** nasce marcado.

## QR das mesas

Em **Configurações > Nuvem**, **QR do cardápio das mesas…** abre a folha A4 (vários cartões por página: nome da casa, "Mesa N" e o QR). O intervalo padrão é 1 até o **Número de mesas**. Casa sem mesas (`usar_mesas` desligado) gera um QR só do cardápio. A folha abre no navegador para imprimir.

O painel do dono (`/painel/`) tem um link **Cardápio** para a mesma página, sem número de mesa.

## Nuvem

| Rota | Quem | O quê |
|---|---|---|
| `POST /v1/cardapio/envio` | token da loja | substitui o catálogo (até 2000 produtos) |
| `GET /v1/cardapio?loja=&mesa=` | público | grupos, preços e a mesa; loja inativa ou sem publicação responde 404 |
| `GET /cardapio/` | público | a página |

Código: `src/sync/cardapio_envio.py`, `src/cardapio/`, `src/ui_qt/cardapio_qr.py`, `backend/cardapio.py`, `backend/cardapio_web/`. Esquema **32** (`produtos.mostrar_no_cardapio`). Testes: `tests/test_cardapio.py`.

## Pedido online (só Will Adega)

Na boate o cardápio continua **só consulta**. No **Will Adega**, o cliente pode pedir pelo próprio cardápio:

1. **Ligar** (Configurações > Módulos): "Pedido online pelo cardápio", o **WhatsApp da loja** com DDD, o valor mínimo
   (opcional) e se aceita **retirada na loja**. Precisa do **Delivery** e do **Cardápio digital** ligados. As taxas vêm do
   cadastro de **Bairros** (e da taxa padrão para "outro bairro").
2. **No celular** do cliente: botões **+ / −** em cada produto, a barra "Ver pedido", nome, telefone, endereço, bairro,
   pagamento na entrega (dinheiro com troco, Pix ou cartão) e observação. Ao enviar, o pedido vai para a nuvem e abre o
   **WhatsApp com a mensagem pronta** para a loja. O cardápio mostra depois se o pedido foi confirmado ou recusado.
3. **No caixa**: o botão **🛵 Pedidos online** acende e apita (busca a cada 30 s). **Aceitar** cria a entrega (F6) já
   preenchida: cliente (achado pelo telefone ou cadastrado), itens com o **preço do caixa**, taxa do bairro, troco e o
   recado "Pedido online #N". Depois é o fluxo normal: conferir, emitir (F8), entregador e receber. **Recusar** pede o
   motivo, que o cliente vê no cardápio. Produto que saiu de venda fica de fora e o caixa avisa.

Proteções: o preço vale o do caixa; no máximo 3 pedidos aguardando por telefone (6 por hora) e 120 por hora por loja;
nada é cobrado online. Na nuvem: `backend/pedido_online.py` (tabelas `pedido_online_config` e `pedidos_online`).

