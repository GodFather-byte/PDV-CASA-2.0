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
O workflow Will Restaurante gera um artefato de instalador para revisão, sem publicar na produção.

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

## Etapas seguintes do pedido

2. Adicionais/opções por item com preço no caixa, cozinha e cardápio.
3. Pedido direto da mesa pelo QR, com importação pelo CaixaController.
4. Pix online Mercado Pago com confirmação do servidor, separado das licenças.
5. Cozinha web local para tablet/TV.

iFood e NFC-e permanecem fora do escopo. Os itens acima só devem ser considerados entregues
quando implementados e validados; a edição inicial não os apresenta como disponíveis.
