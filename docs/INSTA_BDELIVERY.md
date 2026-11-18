# Insta-BDelivery: a vitrine de delivery ligada ao caixa

O Insta-BDelivery é o cardápio de delivery com atendente de IA. Ligado ao caixa (Will Adega e Will Restaurante), ele
recebe o catálogo do PDV e devolve os pedidos de entrega e retirada, que caem no botão "🛵 Pedidos online".

## Os dois canais convivem

| Canal | Para quê | Onde configura |
| --- | --- | --- |
| Nuvem do WillPDV | Cardápio por QR, pedido da mesa, painel, licença | Endereço da nuvem e Token da API |
| Insta-BDelivery | Entrega e retirada, com atendente de IA | Insta-BDelivery: endereço e chave |

Um canal fora do ar não esconde os pedidos do outro, e o catálogo sobe para os dois.

## Ligar

1. No painel do Insta-BDelivery: Configurações > Integração com o caixa > Gerar chave de integração. A chave aparece uma
   vez só.
2. No caixa: Configurações > Conexão com a nuvem. Preencha "Insta-BDelivery: endereço da integração" (termina em
   `/api/pdv`) e "Insta-BDelivery: chave da loja".
3. Deixe ligado o módulo "Pedido online" (Parâmetros e módulos).

Na próxima sincronização o catálogo sobe. Só entra na vitrine produto com código numérico, ativo, à venda e com
"mostrar no cardápio" marcado: sem código o caixa não consegue importar o pedido.

## Como o caixa distingue os pedidos

Cada canal tem numeração própria. O pedido do Insta-BDelivery chega com `canal = "insta"` e um `id` negativo (menos o
número dele), que é o valor guardado em `vendas.pedido_online_id`. O recado da entrega começa com "Pedido Insta #N" (o da
nuvem segue "Pedido online #N"), e a lista mostra "Insta #N".

Aceitar, recusar, saiu, entregue e cancelado sobem para o canal do pedido pela mesma fila de avisos
(`pedido_online_aviso`), então o cliente acompanha na página do pedido.

## Limites desta versão

- **Preço:** a vitrine usa o preço base do produto. Promoção por data, dia da semana ou horário e preço gelado não
  aparecem lá. O caixa recalcula ao aceitar, como já faz no pedido da nuvem.
- **Taxa de entrega:** a vitrine cobra a taxa única configurada no Insta-BDelivery; o caixa calcula a dele (bairro ou
  padrão). Se forem diferentes, o recado da entrega traz o total que o cliente viu
  ("Insta-BDelivery: total cobrado R$ ..."). Mantenha as duas taxas iguais.
- **Mesa:** o pedido da mesa continua só no cardápio da nuvem.
- **Desligar:** apagar o endereço ou a chave no caixa para de publicar e de buscar, mas não tira o catálogo da vitrine.
  Para isso, desconecte o PDV no painel do Insta-BDelivery.
