# WillPDV Licenças: o programa que emite as licenças

É um programa **separado do PDV**, só para quem vende o sistema. Você escolhe a loja e o tipo de licença, toca em **Gerar licença** e
copia o código (ou uma mensagem pronta) para mandar ao cliente. Não precisa de Python nem de linha de comando.

Na **1.2.0**, o botão **Central Telegram** abre a central exclusiva do fornecedor:
cadastro de lojas, administradores locais, credenciais de caixa, backup e execução
do bot administrativo. A assinatura permanece no seu PC e a API atual é somente
ponte para lojas migradas. Não faz cobrança. Configuração e implantação:
[Central](CENTRAL_TELEGRAM.md) (o bot do Telegram foi desligado).

Para cobrar mensalidades e renovar pela internet, veja o guia separado
[Cobrança de licenças com Mercado Pago](COBRANCA_LICENCAS_MERCADOPAGO.md). O licenciador continua
disponível para operação manual e liberações excepcionais; não é entregue ao cliente.

> **Não entregue este programa a clientes.** O cliente só recebe o *código* da licença. Quem tem este programa **e a chave de
> segurança** emite licenças.

## Tipos de licença

| Tipo | Quando usar | Validade |
| --- | --- | --- |
| **Mensal** | a loja que paga todo mês (ou a cada 3, 6, 12 meses) | de 1 a 60 **meses de calendário**: 1 mês a partir de 09/10 vai até 09/11 |
| **Permanente** | a loja que comprou o sistema | sem vencimento na prática (100 anos) |
| **Teste** | demonstração para quem ainda não contratou | de 1 a 90 dias |

Como o PDV se comporta: avisa **7 dias antes** de vencer, dá **5 dias de carência** depois do vencimento e só então bloqueia a
entrada (nunca com um turno recente aberto). Renovar é emitir um código novo e mandar de novo: a loja cola no mesmo lugar.

## Instalar

1. No GitHub: aba **Actions > Gerar instalador (Windows)** > clique na execução mais recente (a primeira da lista, com o ✔ verde)
   > role até o fim da página, em **Artifacts** >
   `WillLicencas-Instalador-<versão>-<commit>`. Baixe, extraia o .zip e rode `WillLicencas-Setup-1.2.0.exe`.
2. Se o Windows avisar "protegeu o seu computador", clique em **Mais informações > Executar assim mesmo** (o instalador ainda não
   tem assinatura digital paga).
3. Não pede senha de administrador. Pode ficar instalado junto com o PDV no mesmo computador.

## Primeira vez: a chave de segurança

A chave de segurança é o que prova que a licença é sua. Ela é um arquivo (`licenca_privada.key`) que fica **só neste
computador**, em `C:\Users\SEU_USUARIO\.pdv-casa\`. Abra a aba **Chave de segurança**:

- **Já emitia licenças pelo PC e tem a chave?** Se for o mesmo computador, ela já aparece como *"conferida: combina com a do PDV"*.
  Se for outro, use **Importar chave...** e escolha o arquivo `licenca_privada.key`.
- **Aparece "Esta chave NÃO é a do PDV"?** É uma chave diferente da que o PDV carrega: os caixas recusariam as licenças. Importe a
  chave certa (a que foi usada para criar o PDV).
- **Nunca criou uma chave?** Use **Criar chave nova** e depois coloque a *chave pública* mostrada na tela em `CHAVE_PUBLICA_HEX`
  (arquivo `src/core/licenca.py`) e gere o PDV de novo. **Só faça isso uma vez:** trocar a chave invalida todas as licenças já
  emitidas.
- Faça logo uma **cópia de segurança** (botão da mesma aba, num pendrive). Sem a chave não se emite mais licença, e **ela não está
  no GitHub nem em lugar nenhum além do seu computador e das suas cópias**.

## Emitir uma licença

1. Aba **Emitir licença**. Digite a **loja** (a mesma chave de loja do PDV; as já usadas aparecem na lista).
2. Escolha o **programa**: **WillPDV** ou **E&A Superações** (a edição só de adega). A licença só abre o programa escolhido:
   a do WillPDV não ativa o E&A Superações e vice-versa. As licenças emitidas antes desta opção valem como WillPDV.
3. Escolha **Mensal** (e quantos meses), **Permanente** ou **Teste** (e quantos dias). A tela mostra até quando vale.
4. **Gerar licença**. Aparece o código (`PDVL1....`).
5. **Copiar mensagem pronta para o cliente** (já traz o código e o passo a passo) ou **Copiar código** ou **Salvar em arquivo**.
6. No caixa do cliente: tela de entrada > **Código de licença...** > colar > confirmar.

## Acompanhar e renovar

A aba **Lojas e vencimentos** mostra cada loja uma vez, com a licença mais nova: vermelho = vencida, amarelo = vence em até 7 dias.
Selecione uma loja e toque em **Renovar a selecionada**: o formulário já vem preenchido com o mesmo tipo e prazo.

Ao abrir o programa, uma **faixa no topo** avisa quando há licença vencida (vermelho) ou vencendo em até 7 dias (amarelo). Clique
nela para ir direto à aba das lojas. Ela some sozinha quando você renova.

O histórico fica em `C:\Users\SEU_USUARIO\AppData\Local\WillPDV-Licencas\historico.json` (guarda o código de cada licença emitida).

## Backup (Google Drive)

Aba **Backup**. O histórico só existe neste computador; se o disco morrer, você perde quem vence quando. Para guardar fora:

1. Instale o **Google Drive para computador** e entre na sua conta (o programa não acessa a conta Google nem guarda senha dela).
2. Na aba Backup, toque em **Usar o Google Drive deste computador** (ou **Escolher pasta do backup...** e aponte uma pasta dentro do Meu Drive).
3. Pronto: a cada licença emitida ou removida o programa copia o histórico para `WillPDV-Licencas\historico-AAAA-MM-DD.json` dentro
   da pasta, e o Drive sincroniza sozinho. Ficam as últimas 30 cópias diárias. Dá para desligar o automático na mesma aba.
4. **Fazer backup agora** guarda também a **chave de segurança, criptografada com uma senha sua** (12 caracteres ou mais), em
   `licenca_privada.key.pdvbkp`. A chave nunca vai para a nuvem sem criptografia: quem tem a chave emite licenças. **Anote a senha em
   lugar seguro; sem ela o backup da chave não abre.**

Para recuperar em outro computador: instale o programa, abra a aba Backup e use **Restaurar chave...** (escolha o `.pdvbkp` e digite a
senha) e **Restaurar histórico...** (escolha o `historico-...json`). O que existia antes vira `.bak`. Se o Google Drive estiver fechado
ou sem pasta, o programa avisa na aba Backup e continua emitindo normalmente.

## Conferir um código

Aba **Conferir um código**: cole um código e veja de que loja é, quando foi emitido e até quando vale (útil quando o cliente liga
perguntando por que "não entra").

## Atualizar ou desinstalar

Rode o instalador novo por cima: se o programa estiver aberto o instalador avisa e fecha. A chave e o histórico **não** são apagados
ao atualizar nem ao desinstalar.

## Logotipo

O ícone e as imagens dos instaladores (do PDV e deste programa) ficam em `instalador/`. Para usar a sua marca, troque
`willpdv.ico`, `willpdv-assistente.bmp` (164x314) e `willpdv-assistente-pequena.bmp` (55x55), e os `willlicencas-*` equivalentes, mantendo
os nomes. Para regenerar os desenhos padrão: `pip install pillow` e `python -m tools.gerar_logos`.

## Para quem mantém o sistema

- Código em `licenciador/` (`nucleo.py` = regras, `tela.py` = janela, `autoteste.py`, `app.py` = entrada). Mesmo formato de chave e de
  código do `tools/gerar_licenca.py` (que continua funcionando).
- Gerar localmente no Windows: `pip install pyinstaller` e `python build_licenciador.py` (precisa do Inno Setup 6; sem ele só o `.exe`).
- No GitHub, o job "Programa de licenças" do workflow *Gerar instalador (Windows)* gera, testa (autoteste no `.exe`, instalação
  silenciosa e atualização por cima com o programa aberto) e guarda o instalador como artifact. **Não** vai para a aba Releases.
- Testes: `python -m unittest tests.test_licenciador`.
