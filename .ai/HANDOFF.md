# HANDOFF

## WhatsApp do dono, sem Telegram

- O bot do Telegram saiu do caixa e da central. Tabelas `telegram_chats` e `telegram_fila` ficam no
  banco da loja, sem uso. Fora do repo: apagar o bot no BotFather e `WILLCENTRAL_TELEGRAM_TOKEN`
  no PC do fornecedor. Não há worker de Telegram no Render.
- Fechamento do turno abre `https://wa.me/<número>?text=...` com o resumo do dia (Configurações >
  Nuvem > WhatsApp do dono, vários números). O painel tem **Enviar resumo no WhatsApp**, **Copiar texto**
  e **Baixar PDF** do dia ou do período. A consulta do texto é sob demanda, não um timer.
- Alertas (cancelamento, desconto, sangria, mesa parada, caixa fora do horário, diferença de caixa,
  estoque baixo) vêm dentro do resumo que o celular já pede. Cada um tem **mandar no WhatsApp**.
- Contagem de estoque no PDV compara contado e teórico e mostra a perda. O retrato leva as perdas e a
  conferência por forma para o painel.

## Neon pode dormir

- O caixa só chama o banco da nuvem com pendência (venda, comanda, estoque, cardápio), no fechamento
  do turno, quando o celular pede, ou na manutenção de licença/versão (horas). Sem isso, não há rede.
- Lote padrão **900 s** (`sync_lote_seg`, 60 a 3600). Batimento no máximo a cada 15 min, e só com movimento
  e dentro de `sync_expediente_de`/`ate` (vazio = o dia inteiro).
- `GET /health` e `GET /v1/sync/pedido` não abrem sessão. O pedido do botão **Atualizar agora** fica na
  memória do Render. Leituras repetidas do painel e do cardápio ficam 45 s em memória.
- Aba oculta no painel e no porteiro para de consultar. Porteiro no Wi-Fi do caixa continua ao vivo;
  na nuvem a lista pode atrasar até o lote. O botão pede envio na hora.
- Uma loja 18 h/dia, 1 venda a cada 13 min: cerca de **6 h/dia** e **180 h/mês** com o compute acordado
  (5 min ligado a cada flush de 15). Em 0,25 CU, perto de **45 CU-h/mês**, dentro das 100. Painel deixado
  aberto na tela conta à parte (cerca de 1 consulta por minuto).

## Atualização automática do caixa

- O aviso antigo (`GET /v1/atualizacoes`) continua. O novo fluxo é `GET /v1/atualizacao/ultima?edicao=&canal=estavel`:
  versão, SHA-256, tamanho, URL, notas e assinatura Ed25519 (chave própria, não a da licença).
- O caixa baixa no `--sync` e ao abrir, confere hash e assinatura, e instala com Inno `/VERYSILENT` só sem venda,
  mesa ou comanda aberta. Adiar um dia; obrigatória ou abaixo da mínima não adia. Dados ficam no `%LOCALAPPDATA%`.
  Se a versão nova não confirmar, o script restaura a pasta anterior e abre de novo, junto com `--sync`.
- O arquivo NÃO fica no GitHub privado nem no disco do Render. URL pública (Cloudflare R2) ou
  `PDV_ATUALIZACAO_DIR` num servidor com disco. Guia com o passo a passo: `docs/ATUALIZACAO.md`.
- **Última instalação manual:** os caixas sem este código não se atualizam sozinhos. A chave pública já está
  em `src/atualizacao/manifesto.py`. A semente privada não está no git: guarde em `PDV_ATUALIZACAO_CHAVE`.
- O autoteste do executável lista `src.atualizacao.cliente`, `src.atualizacao.manifesto` e os módulos do
  cardápio (`src.cardapio.*`, `src.sync.cardapio_envio`, `src.ui_qt.cardapio_qr`). Módulo novo em `src/` entra em `MODULOS`.

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

- `sync_quase_tempo_real` (nasce N): com S, o Qt olha a fila local. O lote sobe a cada `sync_lote_seg` (900 s).
  Painel do dono e porteiro continuam opt-in.
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
