# Handoff — Will Restaurante (10/11/2026)

Base: main 98a873fe, versão 1.13.0, esquema 47. Leia .ai/MAPA.md para a arquitetura atual.

## Trabalho em andamento
Pedido do dono: edição willrestaurante; hamburgueria primeiro, depois adicionais, pedido de mesa, Pix e cozinha web.
Branch feat/willrestaurante. Não publicar como entrega completa enquanto as cinco etapas não forem validadas.

Etapa 1: edição com dados/executável/instalador próprios; perfil inicial hamburgueria e seletor limitado
a hamburgueria, pizzaria, a_la_carte e rodizio. Garotas, portaria, porteiro e quartos bloqueados.
Mesas/cozinha/delivery ligados; cardápio e pedido habilitados na configuração, sem contato fictício:
a publicação operacional exige configurar nuvem e WhatsApp real. Pedidos de delivery usam o fluxo existente.
Licença segue o mecanismo atual por edição. Ícone genérico compartilhado com WillPDV.
Etapa 2: grupos/opções comerciais por produto, seleção Qt, preços e nomes congelados por item;
cardápio e nuvem validam IDs/limites e recalculam preços; ticket e fila de preparo mostram escolhas.
Schema 48 aditivo. Estoque/CMV seguem a ficha técnica do produto, sem baixa extra por opção comercial. Guia docs/WILL_RESTAURANTE.md.

## Validação
O ambiente gerenciado não iniciou; alterações feitas pela integração GitHub.
Workflow Will Restaurante valida perfis/pedidos em Python 3.10/3.12 e empacota no Windows.
Não declarar testes locais nem hardware homologado.

## Próximas etapas autorizadas
- Pedido do QR diretamente na mesa, sem desviar do CaixaController.
- Pix de pedido com confirmação automática; cobrança de licenças independente.
- Cozinha web local no molde de src/porteiro.
- Sem iFood e sem NFC-e.

## Cuidados da base preservada
Vários caixas em rede usam BancoRemoto, transações por conexão e fila por terminal (schema 47).
Homologação com dois Windows, térmica e escala de 125% continuam pendentes.
Não registrar segredos; atualização automática ainda depende de PDV_ATUALIZACAO_*.
