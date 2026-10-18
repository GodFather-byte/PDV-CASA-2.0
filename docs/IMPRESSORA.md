# Impressora do caixa (Elgin i9 e outras térmicas)

O WillPDV imprime o cupom em impressora térmica (ESC/POS) pelo **spooler do Windows**: a impressora precisa estar instalada no
Windows (driver da Elgin i9, cabo USB ligado). O PDV manda os dados direto para ela ("RAW"), sem passar pelo Bloco de Notas.

## Se a Elgin i9 não imprime: Assistente de impressora

Configurações > Máquinas > **Assistente de impressora (Elgin i9)** (ou, na Fila de impressão, o botão de mesmo nome).

1. Deixe a impressora **ligada**, com papel, tampa fechada e o **cabo USB** conectado.
2. O assistente lista as impressoras do Windows (a Elgin já vem marcada) e mostra em vermelho/amarelo **o que está errado**:
   * o caixa está em modo "tela" (de fábrica nada sai na impressora);
   * a impressora aparece offline ou pausada no Windows;
   * há documentos presos na fila do Windows;
   * o serviço "Spooler de Impressão" está parado;
   * o nome gravado no PDV não existe no Windows;
   * a fila do PDV tem cupons com erro (e o último erro).
3. Toque em **Configurar e imprimir teste**. Ele grava tudo de uma vez (modo térmica, conexão Windows, 48 colunas, CP850,
   corte) e imprime a página de teste. Vale na hora, sem sair do programa.
4. **Destravar fila do Windows** retoma a fila pausada e, se você quiser, cancela o que ficou preso.
5. Se ainda não sair, **Copiar diagnóstico** e mande o texto para o suporte: ele traz a configuração, as impressoras do Windows
   (porta, driver, situação), a fila do PDV e os erros.

## A Elgin i9 não aparece na lista do assistente

É o caso mais comum: o Windows mostra só "Microsoft Print to PDF", "XPS Document Writer", "OneNote"... A Elgin i9 nunca foi **instalada**
no Windows, e sem isso nada imprime. O assistente avisa isso em vermelho e oferece o botão **Instalar Elgin i9 (driver genérico)**:

1. Ligue a Elgin i9 (luz acesa) e conecte o cabo USB direto no computador (sem hub).
2. Toque em **Instalar Elgin i9 (driver genérico)**. Ele usa a porta USB que o Windows cria ao detectar a impressora (USB001...) e
   instala o driver "Generic / Text Only", que só repassa os comandos do cupom. Se o Windows pedir permissão, aceite.
3. Toque em **Configurar e imprimir teste**.

Se o assistente disser que o Windows não detectou nada na USB, o problema é físico: impressora desligada, cabo ruim ou porta USB.
Também dá para instalar o driver oficial pelo site da Elgin (botão **Impressoras do Windows** abre a tela do Windows). Instalação à mão:
Configurações > Impressoras e scanners > Adicionar > impressora local > porta USB001 > fabricante Generic > modelo "Generic / Text Only".

## Erros comuns do Windows (o PDV agora explica em português)

| Código | Significa | O que fazer |
| --- | --- | --- |
| 1801 | nome da impressora diferente do Windows | escolher a impressora na lista do assistente |
| 1804 | o driver não aceita impressão direta (RAW) | instalar o driver da Elgin (ou "Generic / Text Only") |
| 1722 | serviço Spooler parado | iniciar "Spooler de Impressão" em services.msc |
| 5 | acesso negado | fechar outros programas que usam a impressora; rodar como administrador |
| 1906 / 21 / 6 | impressora desconectada ou não pronta | ligar, conferir cabo e papel |

## Outras conexões

Em Configurações > Máquinas dá para usar também **rede** (IP:9100), **serial** (COM) e **arquivo**. O guia de testes do
instalador está em `INSTALAR_E_TESTAR.md`.
