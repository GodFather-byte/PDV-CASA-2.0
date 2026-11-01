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
