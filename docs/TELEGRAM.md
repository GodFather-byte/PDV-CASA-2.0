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
| Resumo diário agendado (ativo, às 23h locais por padrão) | consolidado do período não enviado: faturamento, vendas, ticket médio, formas de pagamento, cancelamentos, sangrias e diferenças de caixa |

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
| 🧭 Gerencial | o resumo da noite mais a situação da casa agora: mesas abertas e paradas, entregas e alertas por área |
| 🚨 Alertas | o que pede atenção agora (veja "Alertas operacionais" abaixo) |
| 🛒 Comprar | lista do que repor (sem estoque e no ponto de pedido), com a quantidade sugerida |
| 📈 Semana | faturamento dos últimos 7 dias, dia a dia, com o melhor dia |
| 🗓️ Mês | o mês até hoje (faturamento, ticket, média, melhor dia) e a comparação com o mês anterior |
| 🕐 Por hora | como a noite está andando hora a hora, com o pico |
| 👥 Equipe | vendas por garçom/vendedor na noite |
| 💳 Contas | contas a pagar vencidas e dos próximos 7 dias (só se o módulo de contas estiver ligado) |
| 📒 Caderneta | quanto a casa tem a receber e quem mais deve (nome e valor; nunca CPF, telefone ou endereço) |
| 🔎 Produto | explica como buscar um produto |
| 🔐 Licença | situação e validade, sem expor o código |
| 🛟 Suporte | versão, contato com a central e andamento do pedido, sem credenciais |
| 🔄 Renovar | solicita renovação ao fornecedor pela ponte configurada; não cobra nem emite licença |
| ❓ Ajuda | comandos organizados por assunto |

Além dos botões, o dono pode **digitar**:

* `produto skol` (ou só `skol`): preço, estoque, mínimo, último preço de compra e últimos movimentos do produto;
* `mesa 12` ou `comanda 5`: o consumo daquela mesa agora, item a item, com o total.

Tudo é respondido na hora, direto do PDV, enquanto ele estiver ligado e com internet.

Na 1.7.0 há avisos de vencimento e de licença renovada, sem repetir a mesma situação
na mesma data e validade. "Renovada" depende de aumento da validade aplicada no PDV,
não apenas de um pedido. A solicitação pela ponte é opcional e exige aprovação do
caixa pela central; falha de conexão não é mostrada como pedido entregue.
O bot do fornecedor é **outro bot**, sem acesso ao faturamento desta loja:
[configuração da central](CENTRAL_TELEGRAM.md).

A "noite" segue a virada do dia do PDV (Configurações > Configurações > Caixa, opção da hora em que o dia vira; 6h por padrão): a venda das 2h da manhã
conta na noite que começou na véspera.

## Resumo diário às 23h locais

O agendamento nasce **ativo às 23:00, no relógio local do computador**. Isso não liga o bot:
continua exigindo token, Telegram ligado e celular do dono explicitamente pareado.
Em **Configurações > Telegram**, edite o horário e a opção
**Resumo diário**, depois use **Salvar resumo**. A aba geral Telegram também oferece
os dois campos. Depois da aplicação inicial descrita abaixo, horário vazio ou resumo
desativado pausam o envio. Desligar o Telegram pausa também a fila já existente.

**Primeira atualização:** por decisão explícita do dono, tanto instalações novas quanto
bancos antigos recebem **23:00 e resumo ativo uma única vez**, incluindo horários antigos
personalizados ou vazios. A aplicação é transacional e grava a marca
`telegram_resumo_23h_aplicado=S`, antes de abrir/salvar os campos de configuração, e não
espera o agendador rodar. Depois disso, alterações manuais de horário e opt-out são
preservadas em reinícios e atualizações posteriores. Essa migração **não altera
`telegram_ativo`**, token nem pareamentos: não liga um bot sem consentimento.

O automático usa um **intervalo local com datas e horas completas**, não a “noite”
operacional dos botões Resumo/Ontem. O início é incluído, o fim é exclusivo. O primeiro
intervalo começa à meia-noite do dia do pareamento; os seguintes começam no último corte
confirmado e terminam no horário agendado mais recente já vencido. Assim a venda exatamente
às 23:00 entra no próximo intervalo, sem sumir nem contar duas vezes. Cada resumo informa
a **última atualização local** dos dados. O envio não espera o fechamento de um turno.

**PC desligado por vários dias:** ao voltar, o PDV prepara **um único resumo consolidado**
até o último horário vencido, explicando as datas cobertas, sem disparar um resumo por dia
perdido. Se ainda não deu o horário de hoje, recupera até o corte de ontem. Dados posteriores
ao corte ficam para o próximo agendamento. Sem internet, o resumo permanece pendente, mesmo
após 48 horas ou reinício; novos dias vencidos ampliam esse mesmo pendente antes da primeira
entrega. A janela mostra o período pendente e o último envio confirmado, sem pop-ups periódicos.

A fila existente registra sucesso por celular. Se um dono já recebeu e outro falhou, o texto
desse intervalo fica fixo e o primeiro não recebe de novo na retomada; dias novos ficam para
**mais um consolidado**, não um lote por dia. Somente celulares pareados que participavam
da criação do intervalo podem recebê-lo; chats estranhos não recebem dados. Celulares
removidos não recebem mais. Um bloqueio do bot remove o celular; se nenhum recebeu, o período
não é marcado como enviado. Nesse caso, pareie novamente e aguarde a retomada.

Não se marca envio antes da resposta de sucesso real do Telegram. Ainda assim, a Bot API
não oferece *exactly-once*: queda depois que o Telegram aceitou e antes de salvar o recibo
local pode repetir uma mensagem. Na atualização de instalações antigas, a marca antiga
não era prova de entrega (era gravada ao enfileirar): o primeiro consolidado recupera desde
o dia do pareamento mais antigo e **pode incluir dados que já chegaram pelo agendador antigo**.
Nenhum destes resumos financeiros vai ao fornecedor ou à central.

### Devoluções e bruto histórico

O diário agendado e os botões Resumo/Ontem/Gerencial mantêm o **faturamento bruto histórico**
das vendas originais e mostram **REEMBOLSOS** separadamente, pela data local em que o
reembolso foi registrado, não pela data da venda. O corte inclui o início e exclui o fim:
um reembolso exatamente às 23h entra no intervalo seguinte. O **líquido gerencial do
período** é bruto menos os reembolsos registrados no período; pode ser negativo quando
se devolve uma venda antiga e não equivale ao saldo da gaveta nem a conciliação bancária.
Créditos em outros modos são discriminados e não significam saída de dinheiro.

Reembolso em dinheiro já gera saída de caixa. Por isso o resumo identifica que o total
de saídas **inclui reembolsos**, sem deduzi-los novamente desse total ou da conferência.
Reembolso externo é **declaração do operador**, nunca prova de estorno no banco.

## Alertas operacionais

O botão **🚨 Alertas** (ou `alertas`, `avisos`, `pendências`) e o painel **Alertas da casa** do PDV mostram a mesma
lista, montada só com o banco deste caixa, sem rede e sem gravar nada. Atualiza quando o dono pede (botão ou F5); o
bot **não** manda esses alertas sozinho, para não virar spam. Os avisos automáticos continuam só os de sempre (estoque
que cruzou o mínimo, cancelamento, fechamento, licença), pela fila com repetição controlada.

| Área | Quando aparece | Nível |
| --- | --- | --- |
| Estoque | produto controlado zerado (ruptura) | crítico |
| Estoque | saldo até o mínimo cadastrado (ponto de pedido), com a reposição sugerida | atenção |
| Mesas/comandas | aberta sem lançamento há mais que `tempo_inatividade_min` (o mesmo do painel de mesas; 0 desliga; só com mesas ligadas) | atenção |
| Entregas | entregas em aberto e há quanto tempo a mais antiga foi pedida (só com delivery ligado) | informativo |
| Impressão | documento com erro / impressora sem responder / fila aguardando | crítico / atenção / informativo |
| Telegram | aviso não entregue ou fila parada por falta de conexão | atenção / informativo |
| Painel na nuvem | último envio falhou ou vendas aguardando envio (só com o painel ligado) | atenção / informativo |
| Integrações | iFood/NFC-e em preparação (nunca operam nesta versão) ou com configuração inválida | informativo / atenção |

Não há limite novo inventado: cada regra usa a configuração que a tela correspondente já usa, e nenhuma bloqueia venda.
Os alertas não trazem valores em dinheiro nem o texto técnico dos erros, e nada disso vai para a central do fornecedor.

No PDV, o painel respeita o acesso de quem está logado, por seção: **Relatórios de estoque** (`rel_estoque`) mostra a
área de estoque e **Relatórios informativos** (`rel_informativos`) mostra o resto. Quem não tem nenhum dos dois não abre o
painel; com só um, vê só aquela parte. A permissão é conferida de novo no banco a cada atualização e ao reabrir a janela.
No Telegram, só o chat pareado do dono recebe; outro chat ouve "Este bot é privado".

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
O resumo diário também pode ser ativado/pausado e ter seu horário editado diretamente
na própria janela Telegram.

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
  (pareamento, fila, comandos e as duas threads de segundo plano), `src/ui_qt/telegram.py` (a tela).
- Tabelas `telegram_chats` e `telegram_fila` (esquema v11); chaves `telegram_*` em `config`; módulo de acesso `cfg_telegram` (nível 4).
- O PDV só faz conexões de **saída** para `api.telegram.org:443` (envio e *long polling* de 25 s). Se a rede da loja usa proxy ou
  firewall, libere esse endereço.
- Testes: `python -m unittest tests.test_telegram` (usa um Telegram falso; nada vai à internet).
