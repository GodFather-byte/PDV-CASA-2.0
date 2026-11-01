# HANDOFF

## Estado

- PDV **1.9.0**, esquema **31**, interface Qt (PySide6); licenciador Tkinter.
- Dinheiro em centavos, venda exclusivamente pelo CaixaController. Duas edições: WillPDV e E&A Superações.
- Este trabalho não muda a versão do executável nem o esquema do banco.

## Revisão: cinco correções

- Confirmação de envio compara os dados enviados com o estado atual, em transação curta fora do HTTP.
  Cancelamento durante a resposta continua pendente; UUIDs estranhos na resposta não retiram outras vendas da fila.
- Painel revoga sessões ao desativar loja e confere estado ativo em todas as consultas autenticadas.
- Limitador de login tem teto de chaves e de falhas por chave, sem expulsar bloqueios vigentes. Saturação recusa
  chaves novas até liberar espaço; nomes/senhas têm tamanho máximo.
- Contas editadas validam a combinação final de entrada/quitação antes de gravar.
- Vendas na nuvem usam upsert SQLite/PostgreSQL: lotes repetidos e envios concorrentes não duplicam o UUID.
  Cancelamento é definitivo: envio antigo de venda fechada não o sobrescreve.

## Nuvem quase em tempo real

- Configurações > Nuvem > **Sincronização automática quase em tempo real** (`sync_quase_tempo_real`, nasce N).
  Com S, ServicoSincronizacao inicia com o Qt e envia em 5 s com conexão própria na thread; dispensa iniciar --sync.
  Trava por banco e horário compartilhado evitam envio simultâneo/repetido com um --sync existente.
- Ligar/desligar vale sem reiniciar. Painel do dono precisa estar ligado para enviar vendas, caixa e estoque;
  porteiro precisa estar ligado com PIN para comandas abertas. Sem conexão, vendas permanecem pendentes.
- Retrato informa atualização em 5 s para o painel visível no celular (senão 30 s). Porteiro envia mudanças em 5 s
  nesse modo; consulta da lista do porteiro continua periódica. Falhas aumentam a espera. Render grátis pode dormir.
- Falha de consulta de licença não impede tentar painel/porteiro. Intervalo normal aceita 5 a 3600 s (padrão 60).
- Guias: docs/NUVEM.md, docs/PAINEL_DONO.md. Ainda é necessário atualizar o programa do PC para usar as opções novas.

## Porteiro no iPhone/iPad

- Botão **Instalar no iPhone/iPad** mostra o caminho do Safari: Compartilhar > Adicionar à Tela de Início.
  Não aparece em standalone; instalação nativa Android preservada. Código: src/porteiro/web/instalacao.js.
- A mesma página é servida no caixa e na nuvem. Manifesto e ícone Apple preservados; caches atualizados.
  HTTP local tem limitações; preferir HTTPS da nuvem. Guia: docs/PORTEIRO.md.

## Validação e homologação

- Regressões nos testes do painel, limpeza, contas, sincronização, porteiro e Qt. JS:
  `node --test tests/test_porteiro_instalacao.cjs` (7 cenários de iPhone/iPad/Android).
- CI inclui concorrência de UUID no PostgreSQL e suíte completa Windows/Linux em Python 3.10/3.12.
- Homologar em iPhone físico, Qt no balcão e ESP32 real. Quartos só contam tempo; cliente paga antes no caixa.
  Esquema 31, cartões, aviso aos 5 min e campainha em docs/QUARTOS.md.
- Cobrança Mercado Pago exige MP_ACCESS_TOKEN e MP_WEBHOOK_SECRET; e-mail exige BREVO_API_KEY e EMAIL_FROM.
- Devolução continua sem pré-pago/rodízio; bruto, CMV e comissões históricos não são estornados automaticamente.
  Essa evolução de produto fica fora destas cinco correções. Ver docs/DEVOLUCOES.md.
