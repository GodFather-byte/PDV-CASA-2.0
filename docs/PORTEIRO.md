# Porteiro no celular

O porteiro consulta, no Wi-Fi do clube ou pelo 4G, se a comanda ainda tem valor em aberto. Quem liga
isso é o caixa em PySide6. A página no celular só olha: não fecha conta, não lança item e não mexe
no pagamento.

## Ligar

1. No caixa (a janela PySide6), abra **☰ Operações → Porteiro no celular**. O mesmo atalho está no
   menu principal. O PIN fica nesta tela, não em Configurações.
2. Marque **Ligado**, escolha a porta (o padrão é **8765**) e defina um PIN de 4 a 8 números.
3. Salve. A tela mostra o endereço, por exemplo `http://192.168.0.15:8765/porteiro`, e um QR.
4. O caixa precisa ficar com o WillPDV aberto. Fechar o programa desliga a página.

Se o Windows pedir permissão de rede para o Python ou para o WillPDV, aceite na rede **privada**
(o Wi-Fi do clube). Não é preciso liberar na internet.

O celular no **Wi-Fi do clube** abre o endereço do QR (o caixa responde na hora). Se o Wi-Fi não
chega na porta, use o endereço **Pelo 4G** que a mesma tela mostra: a página fica na nuvem
(`https://willpdv-nuvem-6sp0.onrender.com/porteiro/?loja=CHAVE-DA-LOJA`, com a chave desta loja).
O caixa precisa ter internet e a nuvem configurada (Configurações > Nuvem: endereço, token e chave
da loja). Quando a lista de comandas muda, o retrato entra no mesmo lote da nuvem (padrão 15
minutos), não a cada segundo: assim o banco dorme. **Atualizar agora** pede o envio na hora.
O Wi-Fi do caixa continua ao vivo. O PIN é o mesmo; o token da loja não vai para o celular.

## No celular

1. Digite o PIN. Sem ele, a página não informa comandas.
2. A primeira tela é a lista das **comandas abertas**: número, quanto ainda deve, total da conta
   se for diferente, e a hora em que abriu. A tela mostra **última atualização HH:MM**.
   **Atualizar agora**, na nuvem, pede ao caixa um envio e espera cerca de 30 s; no Wi-Fi, relê o caixa.
   A lista sozinha atualiza a cada 20 s no Wi-Fi e cerca de 1 min na nuvem, e para com a aba oculta.
   Tocar numa comanda abre o detalhe.
   Comanda de garota não entra nessa lista: é a que tem comissão lançada e ainda pendente
   (o mesmo cartão rosa do caixa). Mesa também não entra aqui.
3. **Consultar número** continua disponível para uma comanda ou mesa específica, inclusive a da
   garota. Um leitor que digita o número e dá Enter também serve. O botão **Mesa** consulta mesa
   (`M5`) em vez de comanda. A página tenta o caixa na rede local primeiro. Se ele não responder,
   usa a nuvem sozinha. Embaixo do resultado aparece de onde veio e a hora, por exemplo
   **No caixa · agora, no caixa** ou **Na nuvem · atualizado há 30s**.
3. A resposta ocupa a tela:
   - **LIBERADA**, em verde: nada a cobrar (sem conta, conta paga, vazia ou já recebida).
   - **DEVENDO**, em vermelho: o valor que ainda falta, o que já foi recebido e a lista dos itens.
4. **Nova consulta** lê a próxima. O saldo é o do caixa naquela hora.

A câmera do próprio navegador só abre em endereço seguro (`https`). No Wi-Fi, em `http`, use o
teclado ou o leitor. O aviso na tela explica isso.

### Deixar na tela inicial

- **iPhone/iPad:** abra no Safari e toque em **Instalar no iPhone/iPad** no topo do porteiro.
  A página mostra as etapas: **Compartilhar → Adicionar à Tela de Início → Adicionar**.
  Se aparecer **Abrir como App**, mantenha ativado. O iPhone não permite abrir esse menu automaticamente.
  Se a opção não estiver visível, role as ações do menu Compartilhar. O botão de ajuda não aparece
  quando o porteiro já está aberto como aplicativo. Ao abrir o ícone pela primeira vez, informe
  novamente a loja e o PIN, se solicitado.
  Prefira o endereço HTTPS da nuvem: em HTTP na rede local pode haver somente um atalho,
  sem câmera e sem service worker.
- **Android:** no Chrome, o menu pode oferecer **Instalar app** ou **Adicionar à tela inicial**.
  O Chrome só trata como aplicativo instalável em endereço seguro; em `http://` da rede local o
  atalho abre do mesmo jeito no navegador. A página tem manifesto e service worker para quando o
  navegador permitir a instalação.

O service worker guarda só o visual da página. O saldo **não** fica gravado no celular: cada
consulta vai ao caixa ou à nuvem. Sem os dois, a tela avisa que não há ligação.

## 4G e a nuvem

A nuvem (Render, plano grátis) **dorme** quando ninguém chama. A primeira abertura pelo 4G, depois
de um tempo parada, pode levar cerca de um minuto para acordar. A consulta mostra o último retrato
que o caixa conseguiu enviar, com a idade ("atualizado há 30s", ou mais, se o caixa ficou sem
internet). Não é a conta ao vivo: quem está no Wi-Fi do caixa vê o valor na hora; quem está no 4G
vê o que subiu por último.

O plano grátis aguenta esse uso: o caixa manda um retrato pequeno (só comandas e mesas abertas) e
não reenvia a mesma foto a todo instante. A consulta na nuvem é só leitura, de uma loja por vez, com
o PIN e um limite de tentativas erradas.

## O que o porteiro não faz

Não existe botão de fechar, pagar ou cancelar. A porta HTTP também não aceita esses pedidos.
Cinco PINs errados seguidos travam o aparelho por um minuto.

O PIN fica só como hash no caixa. Não commite banco, `.env` nem senha. A página não sai para a
internet: quem está fora do Wi-Fi do clube não alcança o endereço.
