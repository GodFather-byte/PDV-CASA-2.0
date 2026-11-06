# Adega / depósito de bebidas: guia de implantação

Checklist para instalar o WillPDV numa adega, do zero até a primeira venda, e o que dizer ao dono. As regras de cada
recurso (gelada, atacado, cascos, fardos, agrupamento) estão detalhadas em [ESTOQUE.md](ESTOQUE.md), seção
"Operação de adega"; o painel do celular em [PAINEL_DONO.md](PAINEL_DONO.md).

Diagnóstico, melhorias entregues, plano em fases e próxima evolução:
[Adega: plano de melhorias e validação](ADEGA_MELHORIAS.md).

## Antes de ir à loja

- [ ] Instalador gerado e testado (`docs/INSTALAR_E_TESTAR.md`); licença emitida para a chave da loja.
- [ ] Leitor de código de barras USB (modo teclado, com Enter no fim), impressora térmica e gaveta: levar os cabos.
- [ ] Planilha de produtos do dono, se ele tiver. Colunas aceitas (qualquer ordem, nomes parecidos valem):
  `Produto`, `Preço` (natural), `Preço gelada`, `Atacado a partir de`, `Preço atacado`, `Código de barras`, `Grupo`,
  `Quantidade` (estoque), `Estoque mínimo`. O modelo sai em Cadastros > Importar produtos > Baixar modelo.
- [ ] Aviso ao dono, por escrito: o sistema emite **cupom NÃO FISCAL**. Não emite NFC-e; a obrigação fiscal da loja é
  responsabilidade dela (contador/SEFAZ).

## Na instalação (ordem sugerida)

1. **Primeiro acesso:** nome da loja e perfil **Adega / depósito de bebidas** (na edição **Will Adega** o perfil
   já vem aplicado e as opções de boate nem aparecem; ver `src/core/edicao.py`). O perfil liga o caixa só de balcão, o
   delivery, a caderneta (fiado), o desconto e o agrupamento de leituras repetidas; cria as categorias BEBIDAS
   (Cervejas, Destilados, Vinhos e espumantes, Refrigerantes, Águas e sucos, Energéticos) e CONVENIÊNCIA (Gelo e carvão,
   Tabacaria, Petiscos, Descartáveis). Tudo ajustável depois em Configurações.
2. **Máquina:** Configurações > Máquinas: marcar leitor óptico, impressora (porta/colunas) e gaveta. Imprimir um teste.
3. **Produtos:** importar a planilha ou cadastrar os principais. Na seção **Adega** do cadastro:
   - *Preço gelada* (0 = não pergunta temperatura). Natural e gelada são o mesmo estoque.
   - *Atacado natural* e *atacado gelada*: quantidade mínima + preço unitário (os dois, ou os dois zero).
   - *Casco*: cadastre antes o produto "CASCO 600ML" (com preço) e vincule-o à bebida retornável.
   - *Fardo / caixa*: botão no cadastro do produto unitário; o fardo nasce com preço e código de barras próprios e baixa
     as unidades. Compra de fardo entra como unidades no estoque.
   - O que não tiver cadastro aparece no caixa como "Cadastrar o produto agora?" no primeiro bipe (nome, preço, categoria,
     estoque e preço gelada opcionais). Operador sem permissão pede senha de supervisor.
4. **Operadores:** além do ADM, um usuário por atendente (Cadastros > Operadores), com o nível certo (quem pode cancelar,
   dar desconto, cadastrar produto). Trocar a senha do ADM.
5. **Formas de pagamento:** conferir Dinheiro, Pix, débito, crédito (taxa do crédito, se cobrar) e deixar ativas só as
   usadas.
6. **Estoque inicial:** Estoque > Lançamento > Estoque inicial (ou a coluna Quantidade da planilha). Contar as latas no
   unitário; fardos fechados contam em unidades.
7. **Backup:** Utilitários > Backup: pasta no pendrive/Drive e senha. Fazer um backup e uma restauração de teste.
8. **Nuvem, licença e painel do dono (sem terminal):** na central do fornecedor (`/central/`), cadastre a loja com o
   programa **Will Adega** e registre a validade ou o plano. Copie o **código de instalação** (começa com `WILL1-`).
   No caixa, na tela de entrada, clique em **Ativar licença ou instalar loja** e cole o código: a nuvem, o envio do
   painel do dono e a licença ficam configurados. Para o celular do dono, use **Gerar senha do painel do dono** no
   detalhe da loja na central e passe o endereço `/painel/`, a loja e a senha. Sem nuvem, use o código de licença do
   Will Licenças no mesmo botão; nada no caixa depende da nuvem.

## Treinamento do operador (10 minutos)

### Logotipo da adega

Em **Configurações > Identificação e contatos**:

1. Clique em **Selecionar** e escolha PNG, JPG/JPEG ou BMP (compatibilidade com logos antigos).
2. Confira o preview e clique em **Salvar esta aba**.
3. Para voltar à identidade textual, use **Remover / padrão** e salve. Antes de salvar,
   **Descartar alterações desta aba** recupera a configuração salva.
4. Reabra o caixa para atualizar o cabeçalho. O nome da loja continua visível.
5. Para o cupom, ative **Configurações > Máquinas > Imprimir o logotipo da loja no cupom**,
   com o modo de impressão **Impressora térmica (ESC/POS)**.

Limites: **5 MiB por arquivo (5.242.880 bytes)** e **16 milhões de pixels**. Imagens inválidas
ou corrompidas são recusadas sem substituir o logo anterior. É necessário instalar as dependências
de `requirements.txt` (Pillow); o instalador gerado com elas inclui esse suporte.

O PDV aplica a orientação da foto, reduz para até **384 × 192 pixels**, sem ampliar nem
distorcer, e compõe transparências sobre branco. Uma cópia BMP normalizada fica na pasta
`identidade/` ao lado do banco (no executável, normalmente `%LOCALAPPDATA%\WILL-ADEGA` no Will Adega e `%LOCALAPPDATA%\WILL-PDV` no WillPDV).
Pode mover ou excluir o original depois de salvar. A referência usa o campo existente da loja,
sem migração. Versões anteriores das cópias ficam preservadas; remover o logo desativa a referência,
não apaga originais ou cópias de segurança.

O logo aparece no **preview**, no **cabeçalho do caixa** e nos documentos do cliente
**cupom, pré-conta e entrega** via ESC/POS. Não é aplicado aos relatórios nem aos documentos
internos. Modos **tela**, **arquivo de texto** e **impressora padrão do Windows** continuam
textuais. Na térmica, a imagem sai em preto e branco; o equipamento precisa aceitar raster
ESC/POS (`GS v 0`). Se não aceitar, desligue a opção de logo dessa máquina. Não há detecção
automática desse suporte. Arquivo perdido/corrompido mantém o nome da loja e não impede a venda
ou a impressão textual; falhas no carregamento térmico são registradas no log.

**Transferência/backup:** o backup atual guarda o banco, não os arquivos de imagem externos.
Ao trocar de computador, selecione novamente o logo (ou preserve a pasta e seu caminho).
Logos BMP legados continuam funcionando; para obter a cópia controlada, remova e salve a
referência antiga, depois selecione e salve novamente o arquivo original.

**Validação manual rápida**

- [ ] Selecionar PNG transparente e JPEG, conferir preview e proporção e salvar.
- [ ] Mover o original, reabrir Configurações/caixa e conferir que o logo permanece.
- [ ] Recusar arquivo corrompido ou maior que 5 MiB sem perder o logo anterior.
- [ ] Remover, descartar a remoção e depois remover/salvar; conferir o fallback no caixa.
- [ ] Imprimir cupom em térmica compatível, ligar/desligar a opção de imagem e conferir o texto.

Reposição pelo giro: ver "Depois da instalação" abaixo.

### Foto dos produtos

Em **Cadastros > Produtos**, abra o produto e vá à aba **Foto**:

- **Escolher arquivo…**: JPG, PNG, BMP ou WEBP de até 8 MB (foto do celular, do site do fornecedor etc.).
- **Buscar pelo código de barras**: procura a foto na base pública Open Food Facts usando o campo *Código de barras*.
  Precisa de internet no computador do caixa (sites `world.openfoodfacts.org` e `images.openfoodfacts.org`). Nem todo
  produto brasileiro tem foto lá; quando não acha, use um arquivo. A foto é de voluntários (licença CC BY-SA):
  **confira se é o produto certo** antes de salvar.
- **Remover foto**. Nada muda até clicar em **Salvar**.

**Muitos produtos de uma vez:** em Cadastros > Produtos, botão **Buscar fotos**. Ele procura pelo código de barras
todos os produtos à venda sem foto, mostra cada foto encontrada com uma marcação e só grava as que ficarem marcadas
ao clicar em **Salvar aprovadas**. Desmarque as que não forem do produto certo. Dá para parar no meio.

A foto é reduzida (até 480 px, JPEG) e guardada **dentro do banco**: entra no backup e acompanha a troca de computador.
No caixa, ela aparece na coluna do pagamento quando o produto é lançado (para o operador conferir o que bipou) e some
quando a venda termina; produto sem foto deixa o espaço livre. No **cardápio online**, a foto da internet vai pelo
endereço dela e a de arquivo vai como miniatura (até cerca de 1,5 MB de miniaturas por envio; o que passar usa a figura
da categoria). A nuvem precisa estar atualizada para aceitar as miniaturas.

### Operação no balcão

| O que | Como |
|---|---|
| Vender | Bipar. `6*` antes do bipe (ou `6*código`) lança 6 de uma vez. Bipes repetidos somam na mesma linha. |
| Natural ou gelada | Aparece a pergunta só em produto com preço gelada: N / G ou clique. |
| Atacado | Automático ao atingir o mínimo do produto (por temperatura). A linha mostra `[Atacado]` e o total da economia. |
| Casco | Produto retornável pergunta quantos cascos cobrar: 0 quando trouxe tudo. O casco entra como linha separada. |
| Mudou a quantidade | Selecione a linha e **Ctrl+Q** (ou Operações > Alterar quantidade do item). Aumentar soma na mesma linha e recalcula o atacado; diminuir pede a mesma autorização e o motivo do cancelamento. Produto com casco só diminui por aqui; para aumentar, bipe de novo (ele pergunta os cascos). |
| Fechar | F12, forma de pagamento, valor recebido (troco calculado), Enter. Cupom imprime se estiver ligado. |
| Fiado | F5 escolhe o cliente (limite por cliente); recebimento na mesma tela sem itens. |
| Entrega | F6: cliente, taxa por bairro, troco para; F8 imprime o pedido. |
| Produto novo no bipe | "Sim" > nome, preço, categoria (estoque e preço gelada opcionais) > Gravar. Já lança. |
| Turno | Abrir com o fundo de troco; sangria (F7) quando a gaveta encher; fechar conferindo o esperado. |

## Depois da instalação

- **Reposição pelo giro** (Estoque > Reposição pelo giro): escolha o caixa, o período de vendas (7, 14 ou 30 dias),
  o prazo de entrega do fornecedor e quantos dias o estoque deve durar depois da entrega. A conta aparece em cada
  produto: `média/dia × (prazo + cobertura) − tem − a caminho → comprar`. Desconta pedidos não entregues dos últimos
  30 dias (pedido esquecido mais velho que isso não segura a compra), arredonda para unidade inteira quando o produto não
  aceita fração e mostra quantos fardos dá, quando o produto tem fardo cadastrado. Sem venda no período, o produto
  abaixo do mínimo usa o dobro do mínimo, com aviso. A escolha fica lembrada. O pedido só nasce se a pessoa confirmar e
  escolher o fornecedor; o saldo só muda na entrega. Use 7 dias para captar fim de semana forte e 30 para um giro
  mais estável; feriado, promoção e período em que faltou o produto não entram na conta.

- Em **Estoque > Visão: Adega**, confira a cobertura estimada em dias e use **Lista de compras** ou
  **Gerar pedido do que falta**, escolhendo Geral/Adega. O recorte Adega combina a classificação com os
  filtros do painel; revise os itens antes da compra. A cobertura usa vendas líquidas dos últimos 30 dias
  e não prevê sazonalidade ou prazo do fornecedor. Sem histórico útil, informa a indisponibilidade.
- Para garantir a inclusão de um produto sem sinais de bebida, associe-o a um subgrupo do grupo **Adega**.
  O reconhecimento automático por configuração, famílias e prefixos do nome é indicativo; confira também Geral.
- Novas vendas registram a regra de preço aplicada por item. Alterar o cadastro depois não muda a explicação
  histórica. Vendas antigas sem retrato são identificadas como legadas, sem inventar faixa ou promoção.
- Conferir no fim do primeiro dia: fechamento do turno bate com a gaveta; estoque dos 5 produtos que mais saem; cupom
  legível; gaveta abre.
- **Promoção da gelada:** na aba Promoções do produto, cada janela (período, dias da semana, horário) tem também o
  campo "Preço gelada". Vale nas mesmas datas/horários da promoção natural; 0 deixa a gelada no preço normal. O
  atacado da gelada continua valendo quando for menor que a promoção.
- Pendências conhecidas (não impedem a operação): sem controle de empréstimo/saldo de cascos por cliente, sem etiqueta de
  gôndola (a Tabela de preços impressa traz natural, gelada e atacado), sem NFC-e.
