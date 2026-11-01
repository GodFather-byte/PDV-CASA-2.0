# HANDOFF

## Cardápio digital (QR da mesa)

- Página pública só consulta: `/cardapio/?loja=CHAVE&mesa=N` (`backend/cardapio.py`, `backend/cardapio_web/`).
  Nome, grupo/subgrupo, preço vigente (promoção e happy hour, horário de Brasília), texto de sugestão e foto só se for
  um endereço http(s). Sem custo, estoque, inativo ou `mostrar_no_cardapio` desmarcado.
- O caixa publica em `POST /v1/cardapio/envio` quando **Configurações > Nuvem > Cardápio digital** está ligado
  (`src/sync/cardapio_envio.py`, na mesma rodada da sincronização). Reenviar substitui; catálogo igual não chama a nuvem.
  Desligar tira o cardápio do ar na rodada seguinte.
- **QR do cardápio das mesas…** gera a folha A4 (1 até `num_mesas`, ou um intervalo). O painel do dono ganhou o link Cardápio.
- Esquema **32**: coluna `produtos.mostrar_no_cardapio` (nasce 1). Guia: `docs/CARDAPIO.md`.
- **O PC do caixa precisa ser atualizado** para publicar o catálogo e imprimir os QR. Só o deploy da nuvem sobe a página;
  sem o caixa novo ela responde que o cardápio ainda não foi publicado.

## Nuvem quase em tempo real

- `sync_quase_tempo_real` (nasce N): com S, o Qt envia a cada 5 s. Painel do dono e porteiro continuam opt-in.
  Guias: `docs/NUVEM.md`, `docs/PAINEL_DONO.md`.

## Porteiro

- `/porteiro` no caixa e na nuvem. Lista as comandas abertas sem a da garota. No iPhone, o botão explica
  Compartilhar > Adicionar à Tela de Início. Guia: `docs/PORTEIRO.md`.

## Estado

- PDV **1.9.0**, esquema **32**. Interface do PDV só Qt. Licenciador em Tkinter. Dinheiro em centavos.
- Duas edições: WillPDV e E&A Superações. Cupom não fiscal.

## Pendências para produção

- Atualizar o PDV da loja para o cardápio, o sync de 5 s e o restante que saiu depois do instalador em uso.
- Homologar Qt no balcão, iPhone físico e a campainha ESP32. Quartos: `docs/QUARTOS.md`.
- Cobrança Mercado Pago: `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`. E-mail: `BREVO_API_KEY` e `EMAIL_FROM`.
- Devolução não atende pré-pago nem rodízio. Bruto, CMV e comissões históricos não são estornados por devolução.
