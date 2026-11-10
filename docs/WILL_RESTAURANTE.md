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

## Etapas seguintes do pedido

2. Adicionais/opções por item com preço no caixa, cozinha e cardápio.
3. Pedido direto da mesa pelo QR, com importação pelo CaixaController.
4. Pix online Mercado Pago com confirmação do servidor, separado das licenças.
5. Cozinha web local para tablet/TV.

iFood e NFC-e permanecem fora do escopo. Os itens acima só devem ser considerados entregues
quando implementados e validados; a edição inicial não os apresenta como disponíveis.
