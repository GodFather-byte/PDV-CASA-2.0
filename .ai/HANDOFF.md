# Handoff — Will Restaurante (10/11/2026)

## Branch e escopo
Branch feat/willrestaurante, PR #70, base main 98a873fe (1.13.0).
Pedido do dono: edição restaurante, adicionais, QR da mesa e cozinha web.
Pix online foi adiado pelo dono ("sem pix na tela por enquanto"); não acrescentar pagamento/QR online.
iFood e NFC-e fora do escopo. Não publicar sem terminar a validação do PR.

## Implementação
- willrestaurante: pasta WILL-RESTAURANTE, executável/instalador próprios e licença por edição.
  Perfil inicial hamburgueria; seletor limitado a hamburgueria, pizzaria, a_la_carte e rodizio.
  Quartos, garotas, porteiro e portaria bloqueados. Mesas/cozinha/delivery ligados.
  Cardápio/pedido habilitados na configuração; publicação operacional exige nuvem e WhatsApp reais.
- Adicionais comerciais: grupos com mínimo/máximo, nomes e preços congelados por item.
  Caixa, ticket, fila de preparo e cardápio levam escolhas. Servidor calcula pelo catálogo.
  Estoque e CMV seguem a ficha técnica; não há baixa extra de insumo por opção comercial.
- QR da mesa: valida edição e limites, operador confirma, soma na conta pelo CaixaController.
  pedidos_mesa_importados deduplica e confirma cada pedido, inclusive cancelamento.
- Cozinha web: src/cozinha, servidor só no principal, porta 8766, PIN hash próprio, sessão TV somente leitura.
  Configuração pelo botão Tablet / TV na cozinha Qt, com cfg_configuracoes e operador util_cozinha.
  Status muda por transição explícita (sem duplo avanço); sem pagamentos e sem comandos offline.
  Empacotamento copia cozinha_web; módulos novos entram em src.autoteste.MODULOS.
- Entrega candidata 1.14.0. Schema 49: v48 adiciona opções/retrato; v49 adiciona importação de mesa. Migrações aditivas.

## Validação e limites
O ambiente gerenciado falhou ao iniciar. Escrita/testes pelo GitHub e Actions; não declarar teste local.
Etapas 1/2 passaram no build/autoteste Windows e testes Python 3.10/3.12.
Etapa 3 passou em 209 testes Python 3.10/3.12; acompanhar os builds e a matriz completa do PR.
A regressão completa identificou incompatibilidade ao ampliar o JSON v1 de preços; a correção
mantém esse contrato sem campos extras, usando opcoes_json/adicionais_cent nas colunas próprias.
Cozinha web acrescenta testes de sessão, TV, CSRF, revogação, PIN, cancelamento e transição concorrente.
Homologação real em tablet/TV, impressora, dois Windows e escala 125% continua pendente.

Guia: docs/WILL_RESTAURANTE.md. Localização: .ai/MAPA.md.
A base de vários caixas (BancoRemoto/transações/fila por terminal, v47) deve ser preservada.
