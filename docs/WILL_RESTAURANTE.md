# Will Restaurante

A edição `willrestaurante` compartilha o CaixaController com as outras edições e usa dados separados
em `%LOCALAPPDATA%\WILL-RESTAURANTE`. Executável: `WillRestaurante.exe`.
O ícone genérico do WillPDV é compartilhado; a marca textual é WILL RESTAURANTE.

## Etapa 1 — edição e perfis

O primeiro acesso aplica hamburgueria: mesas, cozinha/bar e delivery ligados; quartos, garotas,
portaria e porteiro bloqueados. Cardápio digital e pedido online nascem ligados, mas só publicam
pedidos depois de configurar a nuvem e o WhatsApp real da loja. Nenhum contato fictício é criado.
A aceitação de delivery continua usando o fluxo já existente, sem confirmar pagamento Pix automaticamente.

Nos Primeiros passos, o tipo de negócio permite hamburgueria, pizzaria, à la carte e rodízio.
Trocar o perfil preserva preços e códigos. Reabrir preserva o perfil escolhido e ajustes do dono;
os bloqueios da edição voltam a valer. As categorias iniciais só são acrescentadas, nunca apagam o cadastro.
A licença precisa ser emitida para Will Restaurante, inclusive no cadastro da loja na central.

```bash
python -m src.app --edicao willrestaurante
python build_pdv.py --edicao willrestaurante
python -m unittest tests.test_will_restaurante tests.test_edicao tests.test_perfil tests.test_pedido_online
```

No Windows, `iniciar_will_restaurante.bat` inicia pelo código-fonte.
O instalador tem AppId próprio e não instala sobre a Adega ou o WillPDV.
O workflow Will Restaurante gera instalador e portátil para revisão na branch. Após merge na main,
publica a release ultima-versao-restaurante e o kit da central aponta para esse instalador.

## Etapa 2 — adicionais comerciais por item

Cadastros > Produtos > Adicionais e opções permite grupos com mínimo/máximo de escolhas e preço por unidade.
No caixa, grupos obrigatórios precisam ser escolhidos antes de lançar. O preço e o nome ficam congelados
na linha; mudar o cadastro não altera vendas anteriores. Cancelamento parcial e transferência copiam esse retrato.
O cardápio publica os grupos; a nuvem ignora preços enviados pelo navegador e calcula pelo catálogo.
O ticket da cozinha leva as escolhas e o adicional. Opções com preço zero atendem ao ponto da carne.

Os adicionais são opções comerciais, sem cadastro de insumo próprio. A baixa de ingredientes e o CMV
continuam seguindo a ficha técnica do produto. Não interpretar a escolha de bacon como baixa de um
insumo adicional sem configurar a composição correspondente. Integração de estoque por opção não faz parte desta etapa.

Esquema 48: produto_opcoes e retrato/preço adicional por item; migração aditiva com padrões vazios.
Teste: tests.test_opcoes_produto. Não homologado em impressora física.

## Etapa 3 — pedido pelo QR da mesa

No Will Restaurante, o catálogo publica a quantidade de mesas cadastradas.
O QR existente (`?loja=...&mesa=N`) abre o pedido naquela mesa: sem endereço ou taxa de entrega.
O cliente informa nome e telefone e acompanha a confirmação. A equipe aceita no botão Pedidos online;
só então os itens entram na conta da mesa e seguem para impressão/preparo. Não há lançamento silencioso
na conta de outra pessoa pela internet. Confira a mesa com o cliente antes de aceitar.

Vários pedidos podem somar na mesma mesa. Reenvio mantém a mesma importação, com confirmação durável
para retomar depois de falha de rede. O acerto continua no caixa; preços e serviço da conta são os do PDV.
O número da mesa no QR não é autenticação de presença física. O fluxo mantém a confirmação do operador.

Schema 49: pedidos_mesa_importados. Testes: tests.test_pedido_mesa.
A Adega continua aceitando entrega/retirada; não recebe pedidos de mesa.

## Etapa 5 — cozinha no tablet / TV

No caixa principal, abra Cozinha/Bar > Tablet / TV. Ligue, defina PIN próprio de 6 a 8 números
e selecione o operador que identifica as ações da cozinha (ativo e com acesso util_cozinha).
A configuração exige acesso cfg_configuracoes. A página usa o mesmo Wi-Fi/rede, normalmente
`http://IP-DO-CAIXA:8766/cozinha/`; a tela mostra o endereço e QR. O caixa principal precisa ficar aberto.
No adicional, só o painel Qt é operado; o servidor web permanece no principal.

No tablet, filtre o setor e avance pendente → em preparo → pronto. Sessão TV (`?tv=1`)
é somente leitura no servidor. Itens cancelados ou que já mudaram não aceitam um segundo avanço.
A página não altera preços, pagamentos ou o fechamento. O status pronto usa o estado de preparo
`entregue`, como no Qt; não confirma entrega física ao cliente.

A atualização ocorre a cada 3 segundos, com indicação da última leitura. Sem comunicação,
os botões ficam bloqueados e a fila é identificada como antiga. Não existe fila offline de comandos.
O PIN fica apenas como hash; trocar PIN/operador revoga as sessões. O operador inativo perde acesso.
Nenhum dado de pagamento, custo, telefone ou endereço é devolvido pela API da cozinha.
Há limite de tentativas de PIN e bloqueio de requisições de outra origem. A página foi desenhada
para rede local; não encaminhe esta porta do roteador para a internet.

Comece com um operador dedicado à cozinha. Os subgrupos precisam ter impressão remota ligada,
o mesmo critério do painel Qt. O filtro usa os setores ativos. O navegador pode usar tela cheia.
A API limita cada resposta aos primeiros 300 itens, informa o total e permite filtrar pelo setor.

Testes: tests.test_cozinha_web; o workflow inclui o JS e os arquivos no executável Windows.
Ainda é necessário homologar no tablet/TV e na rede real, incluindo firewall e suspensão do caixa.

## Etapa 4 — Pix adiado

Por orientação posterior do dono, esta entrega não acrescenta Pix online, QR de pagamento nem
confirmação automática no pedido. O acerto continua no caixa/na entrega pelo fluxo existente.
A cobrança de licenças permanece independente.

## Fora do escopo

iFood, NFC-e, Pix online e baixa de insumos específica por opção comercial.
