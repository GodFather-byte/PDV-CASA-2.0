# HANDOFF

## Painel do dono (bar, boate e adega)

- Aba Hoje abre com **Faturamento do mês até agora**, comparado ao mesmo período do mês anterior.
  Atualiza com o resto do painel (30 s, ou 5 s). Aba **Período**: de/até e atalhos (hoje, ontem, 7 dias,
  este mês, mês passado), com faturamento, vendas, ticket médio, taxa de serviço, formas, gráfico por dia
  e totais por mês. Isso sai das vendas já na nuvem. Guia: `docs/PAINEL_DONO.md`.
- Salão (mesas e comandas, garçom, itens), garçons, serviço separado, CMV/grupo/setor e o sumiço da
  comissão de garota dependem do retrato novo (`modulos`). Casa sem `usar_garotas` não vê garota;
  sem `usar_mesas` não vê o salão. Portaria não tem bloco. Caixa antigo: o painel avisa o que falta
  e não mostra seção vazia de boate.
- **Deploy só da nuvem:** mês, período, formas, cancelamentos e estoque que já subiram. **PC da loja:**
  mesas ao vivo, garçom, grupo, setor, CMV e o perfil explícito.

## Cardápio digital (QR da mesa)

- Página pública só consulta: `/cardapio/?loja=CHAVE&mesa=N` (`backend/cardapio.py`, `backend/cardapio_web/`).
  Nome, grupo/subgrupo, preço vigente (promoção e happy hour, horário de Brasília), texto de sugestão e foto só se for
  um endereço http(s). Sem custo, estoque, inativo ou `mostrar_no_cardapio` desmarcado.
- O caixa publica em `POST /v1/cardapio/envio` quando **Configurações > Nuvem > Cardápio digital** está ligado
  (`src/sync/cardapio_envio.py`, na mesma rodada da sincronização). Reenviar substitui; catálogo igual não chama a nuvem.
  Desligar tira o cardápio do ar na rodada seguinte.
- **QR do cardápio das mesas…** gera a folha A4 (1 até `num_mesas`, ou um intervalo). O painel do dono ganhou o link Cardápio.
- Esquema **33**. Coluna `produtos.mostrar_no_cardapio` (nasce 1). Guia: `docs/CARDAPIO.md`.
- **O PC do caixa precisa ser atualizado** para publicar o catálogo e imprimir os QR. Só o deploy da nuvem sobe a página;
  sem o caixa novo ela responde que o cardápio ainda não foi publicado.

## Nuvem quase em tempo real

- `sync_quase_tempo_real` (nasce N): com S, o Qt envia a cada 5 s. Painel do dono e porteiro continuam opt-in.
  Guias: `docs/NUVEM.md`, `docs/PAINEL_DONO.md`.

## Porteiro

- `/porteiro` no caixa e na nuvem. Lista as comandas abertas sem a da garota. No iPhone, o botão explica
  Compartilhar > Adicionar à Tela de Início. Guia: `docs/PORTEIRO.md`.

## Entrega 1.10.0

- Painel separa bruto, devoluções e líquido; ledger imutável com ACK próprio e custos congelados apenas para novas vendas.
- Custos recuperados e comissão dos itens são referências analíticas; não alteram salários, pagamentos nem CMV histórico.
- Sincronização usa revisão persistente, filas e batimento de 45 s; indicador Qt mostra confirmação e pendências.
- Esquema 33 adiciona revisão, ACK de devoluções e custos dos itens; migração preserva dados e gera backup.
- Dependências fixadas com hashes; workflows validam instalação. Build inclui módulos do autoteste e tzdata (fuso no Windows). Deploy verifica SHA público em /v1/versao.
- Guias: docs/ENTREGA_1_10.md e docs/HOMOLOGACAO_BALCAO.md. Equipamentos físicos ainda pendentes.
- CaixaController mantém entrada pública; cálculo e divisão delegados a módulos menores.

## Estado

- PDV **1.10.0**, esquema **33**. Interface do PDV só Qt. Licenciador em Tkinter. Dinheiro em centavos.
- Duas edições: WillPDV e E&A Superações. Cupom não fiscal.

## Pendências para produção

- Atualizar o PDV da loja para o cardápio, o sync de 5 s e o restante que saiu depois do instalador em uso.
- Homologar Qt no balcão, iPhone físico e a campainha ESP32. Quartos: `docs/QUARTOS.md`.
- Cobrança Mercado Pago: `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`. E-mail: `BREVO_API_KEY` e `EMAIL_FROM`.
- Devolução não atende pré-pago nem rodízio. O painel mostra devoluções separadamente; CMV e pagamentos de comissões históricos não são reescritos.
