# Telegram do dono: acompanhar a casa pelo celular

O dono recebe no Telegram o que acontece no caixa e toca em botões para ver vendas, caixa e estoque a qualquer hora.
Não precisa de servidor, de abrir porta no computador nem de número de telefone para o bot. Leva uns 5 minutos, uma vez só.

## O que o dono recebe sozinho

| Aviso | Exemplo |
| --- | --- |
| Caixa aberto | `🟢 Caixa aberto — turno 2 · Operador: ANA · Fundo de caixa: R$ 100,00` |
| Caixa fechado, com a diferença | `🔴 Caixa fechado — turno 2 · Vendido: R$ 8.420,00 · Dinheiro esperado/contado · ⚖️ faltou R$ 20,00` |
| Cupom cancelado | `❌ Cupom cancelado — Comanda 45 · R$ 132,00 · Por: ANA · Motivo: cliente foi embora` |
| Item cancelado | `❌ Item cancelado — Comanda 45 · 3x SKOL (R$ 24,00) · Por: ANA · Motivo: não informado` |
| Sangria e suprimento | `💸 Sangria: R$ 500,00 · Por: ANA · Obs.: fornecedor de gelo` |
| Backup falhou | `⚠️ O backup automático do PDV falhou.` |
| Produto acabando (na hora em que cruza o limite) | `🚨 SKOL ACABOU (sem estoque)` ou `⚠️ VODKA está acabando: restam 4 (mínimo 5)` |
| Cada venda fechada (opcional, vem desligado) | `🧾 Venda — Comanda 45: R$ 132,00 · Pix R$ 132,00 · Por: ANA` |
| Resumo da noite (todo dia, às 7h por padrão) | faturamento, vendas, ticket médio, formas de pagamento, cancelamentos, sangrias e se cada caixa bateu |

No fechamento o dono vê o dinheiro **esperado** e o **contado**: o operador não vê o esperado (a conferência do PDV é cega), mas o
dono vê no celular se sobrou ou faltou.

## Os botões do bot

| Botão | O que mostra |
| --- | --- |
| 📊 Resumo | vendas da noite até agora |
| 📅 Ontem | resumo completo da noite passada |
| 💵 Caixa | turno aberto, quanto vendeu, formas de pagamento e o dinheiro que deveria estar na gaveta |
| 🍺 Mais vendidos | os 10 produtos que mais faturaram na noite |
| 📦 Estoque | produtos zerados e no ponto de pedido |
| 🪑 Abertas | mesas e comandas em aberto e o total na rua |
| ❌ Cancelamentos | cupons e itens cancelados na noite, com motivo e quem cancelou |
| 🛒 Comprar | lista do que repor (sem estoque e no ponto de pedido), com a quantidade sugerida |
| 📈 Semana | faturamento dos últimos 7 dias, dia a dia, com o melhor dia |
| 🗓️ Mês | o mês até hoje (faturamento, ticket, média, melhor dia) e a comparação com o mês anterior |
| 🕐 Por hora | como a noite está andando hora a hora, com o pico |
| 👥 Equipe | vendas por garçom/vendedor na noite |
| 💳 Contas | contas a pagar vencidas e dos próximos 7 dias (só se o módulo de contas estiver ligado) |
| 📒 Caderneta | quanto a casa tem a receber e quem mais deve (nome e valor; nunca CPF, telefone ou endereço) |
| 🔎 Produto | explica como buscar um produto |

Além dos botões, o dono pode **digitar**:

* `produto skol` (ou só `skol`): preço, estoque, mínimo, último preço de compra e últimos movimentos do produto;
* `mesa 12` ou `comanda 5`: o consumo daquela mesa agora, item a item, com o total.

Tudo é respondido na hora, direto do PDV, enquanto ele estiver ligado e com internet.

A "noite" segue a virada do dia do PDV (Configurações > Configurações > Caixa, opção da hora em que o dia vira; 6h por padrão): a venda das 2h da manhã
conta na noite que começou na véspera.

## Passo a passo

**1. Crie o bot (no celular do dono).**
No Telegram, procure **@BotFather** (tem o selo azul), envie `/newbot`, escolha um nome (ex.: *Boate Estrela*) e um usuário que
termine em `bot` (ex.: `boate_estrela_bot`). Ele responde com o **token**, um código longo como
`123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`. Copie.

**2. Conecte no PDV (no computador do caixa).**
Menu **Configurações > Telegram (celular do dono)**. Cole o token e toque em **Conectar**: aparece
*✔ Bot reconhecido: @boate_estrela_bot*.

**3. Pareie o celular.**
Toque em **Gerar código**. Aparece algo como `/start 498499`. No celular, abra a conversa com o seu bot e envie exatamente essa
mensagem. Em poucos segundos a tela mostra o celular na lista e o bot responde *✅ Conectado!* com os botões.

**4. Teste.**
Toque em **Enviar mensagem de teste**. Pronto. Para escolher quais avisos receber (inclusive ligar o aviso de **cada venda**, para ver o dinheiro entrando ao vivo, e o horário do resumo):
**Configurações > Configurações > aba Telegram**.

Quer que um sócio também receba? Repita o passo 3 com o celular dele (gere um código novo).

## Perguntas frequentes

**Isso pode dar ban no meu número, como no WhatsApp?**
Não. Bots são um recurso oficial do Telegram (a "Bot API"): o PDV conversa com o bot pela porta da frente, sem usar o seu número e
sem automatizar a sua conta. O bot não tem número de telefone. O único cuidado é não criar dezenas de bots nem mandar spam, o que
não acontece aqui (são só os avisos da casa).

**Qualquer pessoa que achar o bot consegue ver o faturamento?**
Não. O bot só responde a quem digitou o código de pareamento (vale 10 minutos, é de uso único e some depois de 5 tentativas
erradas). Qualquer outra conversa recebe só *"Este bot é privado"*. Se perder o celular, remova-o em **Configurações > Telegram >
Remover selecionado** (ou, se o token vazou, no @BotFather envie `/revoke` e cole o token novo no PDV).

**O que passa pelo Telegram?**
Totais, nomes de operadores, números de mesa e comanda, nomes de produtos. **Nunca** nome, CPF ou telefone de cliente. As mensagens
passam pelos servidores do Telegram e (como em qualquer bot) não são criptografadas de ponta a ponta: só pareie quem pode ver o
faturamento. As vendas continuam guardadas só no PDV.

**E se a internet cair ou o computador estiver desligado?**
O caixa vende normalmente. Os avisos esperam numa fila e saem quando a internet voltar (avisos com mais de 48 horas são descartados).
Os botões só respondem com o PDV ligado e com internet: a consulta é feita pelo próprio PDV.

**Posso usar o mesmo bot em dois computadores?**
Não: use um bot por loja, em um único computador (o principal). Dois programas escutando o mesmo bot atrapalham um ao outro; a tela
mostra *"Outro programa está usando este bot"* nesse caso.

**Como desligo?**
Desmarque *Telegram ligado* (na tela do Telegram ou em Configurações > Configurações > aba Telegram). Os celulares continuam
pareados; ao ligar de novo volta tudo. Para apagar de vez, remova os celulares da lista.

**O token fica guardado onde?**
No banco do PDV (como as demais configurações) e, portanto, nos backups. Não vai no pacote de suporte nem nos logs. Trate-o como
uma senha.

## Para quem mantém o sistema

- Código: `src/sync/telegram_api.py` (cliente da Bot API, só biblioteca padrão), `src/controllers/notificacoes.py` (grava o aviso
  na fila; nunca levanta erro), `src/controllers/telegram_textos.py` (os textos), `src/controllers/telegram_controller.py`
  (pareamento, fila, comandos e as duas threads de segundo plano), `src/ui/telegram_ui.py` (a tela).
- Tabelas `telegram_chats` e `telegram_fila` (esquema v11); chaves `telegram_*` em `config`; módulo de acesso `cfg_telegram` (nível 4).
- O PDV só faz conexões de **saída** para `api.telegram.org:443` (envio e *long polling* de 25 s). Se a rede da loja usa proxy ou
  firewall, libere esse endereço.
- Testes: `python -m unittest tests.test_telegram` (usa um Telegram falso; nada vai à internet).
