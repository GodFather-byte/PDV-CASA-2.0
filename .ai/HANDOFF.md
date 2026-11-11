# Handoff — Will Restaurante (10/11/2026)

## Esqueci a senha do gerente (11/11/2026, branch `esqueci-a-senha`)
Pedido do dono: recuperar a senha do ADM sem zerar o banco. Regra em `src/core/recuperacao_senha.py`: o caixa
gera um pedido aleatório (8 caracteres, 24 h, em `config`), o fornecedor assina uma liberação `PDVR1...` com a
chave privada das licenças (loja + pedido + prazo) e o caixa confere com a chave pública antes de gravar a senha
nova de um gerente ativo (nível 4). Uma liberação, uma troca; o bloqueio por senha errada some junto.
- Central: `POST /v1/fornecedor/lojas/{chave}/recuperar-senha` (auditada) e formulário em Suporte e caixas.
- Nuvem: `backend/recuperacao_senha.py` guarda a última liberação da loja; o caixa busca em
  `GET /v1/recuperacao-senha?pedido=` com o token da loja. Sem internet, cola o código.
- Ferramenta local: `python -m tools.gerar_licenca recuperar-senha --loja X --pedido Y`.
- Tela: `ui_qt/esqueci_senha.py`, botão "Esqueci a senha" em `ui_qt/login.py`.
- Testes: `tests/test_recuperacao_senha.py` (17). Licença/segurança: revisar o diff antes de publicar.
- Limite: o caixa secundário (rede) usa o banco do principal; não testado nesse arranjo.


## Recibo de acerto conta comissões, não lançamentos (11/11/2026)
Pedido do dono (Casa Verde): o papel mostrava `COMISSÃO (19)` para R$ 440,00, o que parecia R$ 23 por comissão.
`ImpressaoController.recibo_comissao` agora imprime `COMISSÕES: 88 x 5,00` (total ÷ `comissao_valor_ponto`).
Com a comissão em reais, ou total que não fecha em comissões inteiras, continua a quantidade de lançamentos.
Só o papel mudou; valores, banco e telas ficaram iguais. Testes em `test_acerto_garota_shows.py`.


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
Cozinha web já passou no foco Python 3.10/3.12 e instalação no Windows.
Foi escondida também a linha de status do porteiro no restaurante; a edição mantém cozinha visível.
Cozinha web acrescenta testes de sessão, TV, CSRF, revogação, PIN, cancelamento e transição concorrente.
Homologação real em tablet/TV, impressora, dois Windows e escala 125% continua pendente.

Guia: docs/WILL_RESTAURANTE.md. Localização: .ai/MAPA.md.
A base de vários caixas (BancoRemoto/transações/fila por terminal, v47) deve ser preservada.
