# Cobrança automática de licenças WillPDV com Asaas

Guia do fornecedor: funcionamento, custos, configuração, testes e operação.
Referências consultadas em **16/10/2026**. Preços, limites e nomes dos menus podem mudar.

## 1. O que esta versão faz

Você cadastra uma assinatura mensal no Asaas e a vincula à loja no WillPDV.
O Asaas gera as próximas cobranças. Quando o cliente paga, o servidor confere o
pagamento diretamente na API do Asaas, atualiza a validade da loja e entrega uma
licença assinada ao PDV. Não é preciso emitir e enviar um código todo mês.

As decisões desta versão são:

| Assunto | Regra |
| --- | --- |
| Contratação | Uma assinatura mensal por loja, não por computador |
| Valor | Definido por você para cada loja, no cadastro do vínculo |
| Pagamento | Pix/boleto por link: o cliente paga a cada mês |
| Internet | Necessária para receber a renovação, não para cada venda |
| Aviso | Começa 7 dias antes do vencimento da licença |
| Carência | 5 dias depois do vencimento, como no PDV atual |
| Turno aberto | Preserva a exceção atual para turno recente; não encerra o caixa à força |
| Orçamento de infraestrutura | Meta de até R$ 50/mês, sem incluir taxas de recebimento |

**Cobrança recorrente não é débito automático.** Nesta versão, o Asaas gera a cobrança
mensal, mas o cliente precisa pagar o link. Cartão recorrente e Pix Automático com
autorização do pagador são modalidades diferentes, não implementadas aqui.

Não há nesta versão um novo painel web de administração, cadastro automático de
clientes, emissão automática de notas fiscais, troca de planos ou criação de
assinaturas por API. Use o painel do Asaas para o cadastro e os comandos deste
guia para o vínculo e a recuperação. Isso evita colocar um formulário financeiro
e dados de cartão dentro do PDV.

## 2. Entendendo as peças

```text
Você cadastra cliente + assinatura mensal no painel Asaas
                         |
Asaas gera cobrança e disponibiliza link ao cliente
                         |
Cliente paga Pix/boleto
                         |
Asaas envia uma notificação HTTPS (webhook)
                         |
Nossa API autentica e confirma o evento no inbox PostgreSQL (HTTP 200)
                         |
Worker durável consulta a cobrança no Asaas (retentativas + agenda)
                         |
PostgreSQL guarda o pagamento e a validade da loja
                         |
PDV consulta nossa API e recebe uma licença Ed25519 assinada
                         |
PDV verifica a assinatura e continua trabalhando localmente
```

- **Asaas:** recebe o dinheiro na sua conta, gera cobranças e informa os eventos.
- **API WillPDV:** programa hospedado na internet, compartilhado por todas as lojas.
- **PostgreSQL:** guarda vínculos, inbox, agenda, tentativas, cobranças e datas pagas.
- **Worker:** processo do servidor que drena o inbox e concilia assinaturas a cada 6 horas.
- **PDV instalado:** guarda vendas e verifica a licença; não recebe sua chave Asaas.
- **WillPDV Licenças:** continua disponível para licenças manuais e atendimento excepcional.

O sistema não envia as vendas, comandas nem dados de cartão dos clientes do
estabelecimento ao Asaas. O objeto da cobrança é a sua mensalidade do software.
Os dados cadastrais do contratante são preenchidos no painel Asaas.

O cliente de renovação online **já existia** no PDV. Esta integração alimenta a
mesma validade e preserva o formato das licenças, a chave pública e as regras
offline. Não exige migrar o banco SQLite das lojas.

## 3. Quanto custa e o que precisa hospedar

### 3.1 Asaas

Na página oficial consultada, o Asaas informa ausência de mensalidade e de taxa
de adesão no modelo padrão. Há cobranças pelos serviços utilizados, incluindo
recebimentos e notificações, conforme as condições da conta.

Antes de precificar:

1. Acesse sua conta Asaas e confira **Menu do usuário > Taxas**.
2. Anote as taxas de Pix e boleto, prazo de disponibilização e regras promocionais.
3. Confira os custos dos lembretes por e-mail, SMS e WhatsApp antes de habilitá-los.
4. Não conte com antecipação de recebíveis para reduzir custo: é outro serviço.
5. Separe impostos e eventual emissão de nota fiscal do custo desta integração.

Não há uma tabela de taxas fixa no código. Consulte [preços e taxas do Asaas](https://www.asaas.com/precos-e-taxas).

Exemplo **hipotético**, não uma cotação: 20 lojas pagando R$ 99 geram R$ 1.980 brutos.
Se cada recebimento custasse R$ 2 e a infraestrutura R$ 45, sobrariam
R$ 1.895 **antes** de impostos, suporte, notificações e outros custos.

### 3.2 Hospedagem sugerida para começar

**Render com serviço web pago básico + PostgreSQL externo no Neon** permite
reaproveitar a configuração do projeto. A URL fornecida pelo Render já tem HTTPS;
domínio próprio não é obrigatório.

| Item | Planejamento |
| --- | --- |
| API no Render | Confira o preço do menor serviço pago sempre ligado; não confunda plano do workspace com plano do serviço |
| Worker | Processo separado sempre ligado ou comando periódico no servidor; hospedagem gerenciada pode cobrar outro serviço, veja seção 11 |
| Banco no Neon | Plano gratuito pode atender o piloto, dentro das cotas; acompanhe uso e limites |
| HTTPS | Usar o endereço HTTPS fornecido pela hospedagem |
| Backups | Manter cópias externas; não presumir que o plano grátis inclui a retenção necessária |
| Monitoramento | Conferir saúde da API e alertas de webhook; serviços externos podem ter custo |

**A meta de R$ 50 não é uma garantia de preço.** Como referência de orçamento:
se o serviço escolhido custar US$ 7/mês e o dólar do cartão for R$ 5,50, serão
R$ 38,50 antes de IOF, spread e eventuais adicionais. São valores de simulação:
confirme a cotação e o preço no painel antes de contratar. Se o total passar de
R$ 50, não contrate automaticamente: compare um serviço em reais ou reveja o teto.

O Neon gratuito não é uma promessa de disponibilidade para operação comercial.
Reavalie banco pago, backups e suporte conforme a carteira crescer. Não há aqui
uma estimativa de quantidade máxima de lojas: isso requer medir uso e carga reais.

**Não use o Render gratuito para cobrar clientes em produção.** Ele dorme após
inatividade, pode demorar a atender webhooks e tem disco efêmero. A própria
documentação do Render recomenda não usar instâncias gratuitas em produção.
Não guarde o banco de produção no SQLite local do Render.

Consulte [preços do Render](https://render.com/pricing),
[limitações do Render gratuito](https://render.com/docs/free) e
[planos do Neon](https://neon.com/pricing).

Um VPS também é possível, mas exige administrar atualizações, HTTPS, firewall,
processo, banco e backup. Para aprender esta integração, a hospedagem gerenciada
reduz a quantidade de coisas para cuidar.

## 4. Segredos: o que fica onde

| Configuração | Onde fica | Finalidade |
| --- | --- | --- |
| `ASAAS_AMBIENTE` | Servidor e terminal de administração | `sandbox` ou `producao`; padrão `sandbox` |
| `ASAAS_API_KEY` | Apenas servidor/terminal de administração protegido | Consultar a sua conta Asaas |
| `ASAAS_WEBHOOK_TOKEN` | Servidor + configuração do webhook Asaas | Autenticar notificações |
| `PDV_NUVEM_DB_URL` | Servidor/terminal de administração protegido | Endereço e credenciais do PostgreSQL |
| `PDV_API_TOKEN` | Apenas administração | Acesso administrativo existente |
| `PDV_LICENCA_CHAVE` | Servidor | Caminho do arquivo da chave privada de licença |
| Token da loja | PDV daquela loja | Buscar somente a licença da própria loja |

São **segredos diferentes**. Não use a API Key como token do webhook nem como
token de loja. Gere o segredo do webhook, por exemplo, com:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Guarde o resultado em um gerenciador de senhas. Não coloque nenhum segredo em
GitHub, capturas de tela, mensagens de suporte, executável do cliente ou neste
guia. Evite digitar credenciais reais em comandos que ficarão no histórico do
PowerShell; prefira variáveis secretas do provedor. Os exemplos abaixo são
marcadores, não credenciais funcionais.

A chave privada deve ser a mesma que já corresponde à chave pública dos PDVs.
**Não gere um novo par para esta integração:** isso invalidaria as licenças antigas.

## 5. Preparar o servidor

Antes de tudo, faça backup do banco da nuvem e da chave privada.
Se a nuvem já existe, atualize-a; não crie outro banco por engano.

### 5.1 Preparar o ambiente de administração no Windows

Na raiz do repositório, com Python 3.10 ou superior:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Os comandos `python -m backend.lojas ...` precisam apontar para o **mesmo banco
do servidor**. Para testes locais, o padrão é SQLite. Para produção:

```powershell
$env:PDV_NUVEM_DB_URL = "postgresql://USUARIO:SENHA@HOST/BANCO?sslmode=require"
$env:ASAAS_AMBIENTE = "sandbox"
$env:ASAAS_API_KEY = "CONFIGURE_A_CHAVE_DE_TESTES_FORA_DO_HISTORICO"
```

Variáveis definidas no PowerShell valem só naquele terminal. Defini-las no seu PC
não configura o Render e vice-versa.

### 5.2 Render e Neon

O guia [NUVEM.md](NUVEM.md) explica o cadastro no Render e Neon. Para esta integração:

1. Crie ou selecione o PostgreSQL e guarde sua connection string com TLS.
2. No Render, conecte o repositório e use o serviço web Python existente.
3. O blueprint atual é gratuito por padrão: **mude o plano do serviço para pago**
   antes de atender cobranças reais, após conferir o orçamento.
4. Build: `pip install -r backend/requirements.txt`.
5. Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.
6. Configure `PDV_NUVEM_DB_URL`, `PDV_API_TOKEN` e `TZ=America/Sao_Paulo`.
7. Cadastre o arquivo secreto `licenca_privada.key` e configure
   `PDV_LICENCA_CHAVE=/etc/secrets/licenca_privada.key`.
8. Configure `ASAAS_AMBIENTE=sandbox`, a API Key de sandbox e o segredo do webhook.
9. Publique a aplicação e consulte `https://SEU-SERVICO.onrender.com/v1/saude`.
   O resultado esperado é `{"status":"ok"}`.
10. Confira os logs de inicialização e a criação das tabelas no banco.
11. Configure e inicie o worker da seção 11; sem ele, o webhook apenas acumula
    eventos e **não renova licenças**. Este blueprint não cria nem contrata worker.

A saúde verifica o processo da API; **não comprova** a configuração do Asaas,
a chave de assinatura ou a entrega de webhooks. O teste completo está na seção 9.

As tabelas são `assinaturas_asaas`, `cobrancas_asaas`, `eventos_asaas`,
`tarefas_asaas` (inbox e agenda) e `workers_asaas` (última batida).
São criadas na inicialização pelo padrão SQLAlchemy já usado no backend.
Para uma instalação existente, a migração operacional é aditiva: `create_all`
cria somente as duas tabelas novas e seus índices; não altera nem apaga vínculos,
eventos antigos, cobranças ou validades. Eventos já processados continuam
idempotentes. Faça backup e execute, **antes de iniciar API e worker em paralelo**:

```powershell
python -c "import backend.main"
```

O usuário do banco precisa de permissão para criar tabelas/índices nessa etapa.
Essas tabelas não alteram o esquema local de vendas do PDV. Não as apague para
resolver uma falha: elas guardam o histórico necessário à conciliação.

## 6. Cadastrar a loja e a assinatura

### 6.1 Loja no WillPDV

Se já existe, **não recrie**. Se for nova:

```powershell
python -m backend.lojas criar LOJA-CENTRO "Loja Centro"
```

Guarde o token mostrado: ele aparece uma vez. A chave `LOJA-CENTRO` deve ser
a mesma configurada no PDV. O código não permite que o cliente escolha
outra loja usando seu próprio token.

Se a loja tem uma licença manual válida, registre a data paga na nuvem **antes
de vincular ao Asaas**, quando aplicável:

```powershell
python -m backend.lojas assinatura LOJA-CENTRO 2026-11-15
```

Essa validade anterior é preservada como base do vínculo. Não registre uma data
que o cliente não contratou. Depois do vínculo, o comando manual `assinatura`
é recusado para evitar dois controles conflitantes.

### 6.2 Cliente e assinatura no Asaas

1. Use primeiro sua conta de **sandbox**, separada da produção.
2. Cadastre o contratante com os dados exigidos pelo Asaas e contato correto.
   Os dados pessoais ficam no Asaas, não precisam ser copiados para o código.
3. Crie uma assinatura **mensal**. Não escolha parcelamento de uma compra única.
4. Defina o preço combinado e o primeiro vencimento.
5. Escolha Pix ou boleto. Se o painel oferecer modalidade indefinida, assegure
   que a cobrança seja paga por Pix/boleto; cartão não é aceito nesta versão.
6. Configure os avisos ao cliente, conferindo custos antes de habilitá-los.
7. Copie o identificador da assinatura, que começa com `sub_`.
   Se ele não aparecer claramente no painel, consulte a documentação/API do
   Asaas para recuperar o ID; não use o ID `pay_` da cobrança no lugar dele.
8. Confira nome, valor e vencimento antes de vincular. Um vínculo errado pode
   liberar a loja errada; ele não é uma comprovação automática do contratante.

### 6.3 Vincular

Exemplo: R$ 99,00 são **9900 centavos**, não `99` nem `99.00`:

```powershell
python -m backend.lojas cobranca vincular LOJA-CENTRO sub_EXEMPLO 9900
python -m backend.lojas cobranca listar
python -m backend.lojas cobranca conciliar LOJA-CENTRO
```

Substitua `sub_EXEMPLO` pelo ID real do ambiente correto.
O vínculo consulta a assinatura na API e exige:

- loja existente e ainda sem outro vínculo;
- assinatura ativa, mensal e com forma de pagamento permitida;
- valor igual ao informado em centavos;
- assinatura ainda não usada por outra loja.

Vincular **não cria uma nova assinatura, não gera cobrança adicional e não
libera licença sem pagamento**. Conciliar recupera cobranças já geradas.
Não misture sandbox e produção no mesmo banco.

O valor pode ser diferente para cada loja. Alteração posterior de preço,
substituição de assinatura ou migração entre provedores ainda não têm fluxo
administrativo nesta versão. Não edite o banco à mão nem mude o valor no Asaas
sem planejar essa evolução: divergências serão recusadas, não liberadas em silêncio.

## 7. Configurar o webhook no Asaas

Webhook é uma chamada que o Asaas faz à nossa API quando uma cobrança muda.
Não é um endereço de pagamento nem um endereço de callback do navegador.

No ambiente correto do Asaas, abra a configuração de integrações/webhooks:

| Campo | Valor |
| --- | --- |
| URL | `https://SEU-SERVICO.onrender.com/v1/webhooks/asaas` |
| Autenticação | O mesmo segredo de `ASAAS_WEBHOOK_TOKEN` |
| Formato | JSON |
| Envio | Preferir sequencial para facilitar operação inicial |
| Notificações de falha | Seu e-mail administrativo monitorado |
| Estado | Habilitado, fila não pausada |

O Asaas envia o segredo no cabeçalho **`asaas-access-token`**.
Não configure `Authorization: Bearer` no lugar dele.

Selecione os eventos de cobrança necessários à operação, incluindo:

- `PAYMENT_CREATED`, `PAYMENT_UPDATED`, `PAYMENT_CONFIRMED`, `PAYMENT_RECEIVED`;
- `PAYMENT_OVERDUE`, `PAYMENT_DELETED`, `PAYMENT_RESTORED`;
- `PAYMENT_REFUNDED`, `PAYMENT_PARTIALLY_REFUNDED`, `PAYMENT_REFUND_IN_PROGRESS`;
- eventos de chargeback disponíveis na conta.

Confira a lista vigente na [documentação de eventos](https://docs.asaas.com/docs/webhook-para-cobrancas).
O endpoint aceita notificações `PAYMENT_*`; eventos de assinatura não são
necessários para renovar e não devem ser enviados a esse endpoint.
Cancelar a assinatura no painel interrompe a recorrência, mas não apaga
automaticamente o período que já foi pago.

O conteúdo financeiro do webhook **não é usado como comprovante**:
o worker consulta `GET /payments/{id}` no Asaas e verifica cliente, assinatura,
valor, vencimento, meio de pagamento e estado atual.

O recebimento responde 200 com `situacao=enfileirado` **depois** do commit
do inbox, sem nenhuma chamada HTTP ao Asaas. Só guarda ID do evento, tipo,
assinatura e cobrança, não o payload financeiro ou dados pessoais.
Reentrega do mesmo ID retorna `repetido`, sem criar segunda tarefa. ID repetido
com identificadores diferentes é recusado (422). Token incorreto retorna 401;
formato/IDs inválidos retornam 422. Falha do banco retorna 503 para o provedor
reenviar; não há confirmação de um evento não persistido.

HTTP 200 **não significa licença liberada**. Falha remota, credenciais inválidas,
assinatura ainda não vinculada ou divergência financeira ficam no banco com erro,
número de tentativas e próxima execução. O worker tenta novamente após
60, 120, 240, 480, 960, 1920 segundos e depois no máximo a cada 3600 segundos,
sem descartar silenciosamente eventos. Não há Redis, Celery nem fila em memória.
Corrija a causa no servidor/Asaas; não altere valores ou assinatura no banco para
contornar a validação. Veja os indicadores administrativos da seção 11.

**Operação importante:** segundo a documentação consultada, 15 falhas consecutivas
podem pausar a fila, e eventos são retidos por 14 dias. Monitore os alertas,
corrija o problema, reative a fila e concilie as lojas afetadas.

## 8. Configurar o PDV do cliente

Em **Configurações > Nuvem**, informe:

1. URL HTTPS da sua API, por exemplo `https://SEU-SERVICO.onrender.com`.
2. Chave da loja, por exemplo `LOJA-CENTRO`.
3. Token **daquela loja**, gerado no cadastro.
4. Deixe a sincronização/consulta de nuvem habilitada na operação do PDV.

Nunca informe a chave Asaas ou seu token administrativo no caixa.
No executável distribuído, a licença é exigida. Para testar pelo código-fonte,
a exigência precisa estar habilitada (`licenca_exigir = S`).

O cliente de renovação consulta no máximo a cada **6 horas**. Portanto, pagamento
confirmado não significa atualização instantânea da tela de um PDV já aberto.
Quando a entrada está bloqueada, ela força uma tentativa de renovação antes
de pedir o código manual. Sem internet, só o prazo já assinado continua valendo.

Não prometa ao cliente que pagar enquanto estiver totalmente offline libera
o caixa: ele precisa se conectar ao menos para receber a licença nova ou
receber de você um código manual válido.

O link de pagamento é disponibilizado pelo Asaas e pelos canais que você
configurar lá. **Esta versão não adiciona botão de pagamento ao PDV.**

## 9. Testar sem cobrar dinheiro real

Use uma conta Asaas sandbox, banco separado e loja de teste. Credenciais e IDs
de produção não funcionam no sandbox e vice-versa.

### Teste automatizado local

Com as dependências do backend instaladas:

```powershell
python -m pip install httpx
python -m unittest tests.test_cobrancas_asaas tests.test_backend_operacao_asaas tests.test_licenca_nuvem tests.test_nuvem tests.test_licenca tests.test_atualizacoes
```

Os testes simulam a API Asaas e não criam cobranças nem exigem sua chave real.
Eles verificam autenticação, isolamento entre lojas, comparação de valores,
idempotência, estado remoto, calendário, estorno, recuperação paginada e
o recebimento de uma licença assinada pelo cliente PDV, inbox sem HTTP,
falhas de commit, backoff persistido, agenda e retomada após interrupção.
Os testes unitários de operação usam SQLite em memória. O job Linux
`Asaas / PostgreSQL 16` do CI sobe um service container exclusivo e executa também
entregas concorrentes, `SKIP LOCKED`, eventos diferentes para uma assinatura,
falhas de commit e retomada no driver PostgreSQL real.

Para repetir em um PostgreSQL **descartável exclusivo de teste**, configure
`PDV_TESTE_NUVEM_DB_URL` com a conexão e execute os dois módulos de cobrança.
**Nunca aponte para dados reais:** os testes apagam tabelas de lojas e cobranças
do banco indicado. Sem essa variável PostgreSQL, os testes concorrentes são pulados.

### Homologação de ponta a ponta no sandbox

1. Publique API e worker de teste com banco persistente e segredos de sandbox.
2. Cadastre uma loja de teste e uma assinatura mensal Asaas de teste.
3. Vincule o ID `sub_` à loja, com o valor exato.
4. Configure o webhook de teste e verifique o histórico de entregas.
5. Com a cobrança pendente, confirme que a data paga da loja não avança.
6. Simule o recebimento usando os recursos de sandbox documentados pelo Asaas.
   Não faça uma transferência real para tentar pagar uma cobrança de teste.
7. Confira resposta HTTP 200 no histórico do webhook.
8. Aguarde o worker e confira `pronto`, pendências e últimas execuções no endpoint
   administrativo da seção 11. Execute `python -m backend.lojas listar`: a
   validade deve ter avançado depois do processamento.
9. Execute `python -m backend.lojas cobranca conciliar LOJA-TESTE`:
   a validade deve continuar igual, sem acrescentar outro mês.
10. Ligue um PDV de teste à API e confirme a renovação da licença.
11. Desconecte a rede: a licença recebida deve continuar válida dentro do prazo.
12. Simule estorno, confira o recálculo no servidor e a limitação offline abaixo.
13. Teste um token de webhook errado: deve receber 401 e não renovar nada.
14. Registre os resultados sem expor tokens, chave privada ou dados pessoais.

**A validação automatizada não substitui essa homologação.** Não houve
contratação de hospedagem, configuração de conta ou movimentação financeira
por este trabalho. A entrada em produção depende de você executar e aprovar
esse teste com a sua conta.

## 10. Regras da validade

### Período pago

Cada cobrança mensal paga cobre até **um mês de calendário após seu vencimento,
inclusive**. Não são 30 dias fixos nem um mês a cada notificação recebida.

| Vencimento da cobrança | Validade daquela cobrança |
| --- | --- |
| 15/10/2026 | 15/11/2026 |
| 31/01/2026 | 28/02/2026 |
| 31/01/2028 | 29/02/2028 |
| 31/12/2026 | 31/01/2027 |

A regra usa o vencimento informado pelo Asaas, não a data em que o webhook
chegou. Pagamento atrasado não gera automaticamente um mês a partir do dia
em que o cliente resolveu pagar. Não altere vencimentos de cobranças pagas
para estender licenças informalmente.

Ao pagar várias cobranças, vale a maior data coberta, sem somar meses por evento.
Uma cobrança antiga chegando depois não encurta uma licença mais nova.
Uma cobrança futura paga pode liberar o período até sua data final mesmo se
houver outra mensalidade em aberto: este controle não é um bloqueio de todas
as dívidas do cliente. A negociação financeira fica no Asaas.

### Estados que liberam

- `CONFIRMED` e `RECEIVED`, em cobrança não removida e com valor correto.
- `PENDING`, `OVERDUE`, `RECEIVED_IN_CASH`, estados de estorno e demais estados
  não concedem validade. Uma baixa manual em dinheiro não comprova pagamento online.
- Multa/juros não devem ser usados para mudar o valor-base contratado.
  Confira no sandbox como sua conta apresenta cobranças com encargos; valor
  divergente será recusado. Esta versão não negocia descontos, multas ou planos.

### Estorno, cancelamento e offline

No servidor, um pagamento que deixa de estar em estado aceito perde sua
contribuição à validade. Permanecem outras cobranças válidas e a validade manual
que existia antes do vínculo.

**Uma licença já entregue é um documento assinado offline.** Ela não pode ser
encurtada remotamente de imediato. O PDV atual também ignora códigos de renovação
mais curtos. Portanto, após um estorno, o caixa pode continuar usando a licença
que já tem até o prazo e a carência; não há revogação imediata.

Desativar a loja no servidor impede novas consultas autorizadas, mas não apaga
o código offline. Cancelar recorrência não reembolsa automaticamente o cliente,
e reembolsar não substitui o cancelamento da recorrência. Confira ambas as
operações no painel Asaas.

Se você precisar de revogação rápida, será outra regra de produto: licenças
online de duração curta, check-ins e uma política explícita de tolerância.
Isso **não foi ativado**, para preservar o funcionamento offline combinado.

## 11. Rotina de administração e recuperação

### Ver as lojas e os vínculos

```powershell
python -m backend.lojas listar
python -m backend.lojas cobranca listar
```

Use o painel Asaas para consultar links, recebimentos, cobranças vencidas e
contatos do cliente. Não há uma nova tela financeira no PDV.

### Worker e agenda no servidor (obrigatórios para automatizar)

Depois da migração e com as mesmas variáveis `PDV_NUVEM_DB_URL`,
`ASAAS_AMBIENTE` e `ASAAS_API_KEY` da API, execute na raiz do projeto:

```powershell
python -m backend.worker_asaas
```

O comando fica em primeiro plano: configure reinício automático pelo gerenciador
de processos da hospedagem/serviço do sistema. Não basta deixar um terminal do
seu computador aberto. Ele verifica o banco a cada 5 segundos, processa até
100 tarefas por lote e registra batida antes/depois do trabalho. `--pausa` e
`--limite` ajustam esses números. Não inicia thread dentro do Uvicorn nem depende
do tráfego HTTP. API sozinha nunca drena a fila.

**Opção gerenciada:** um serviço de background worker com o mesmo repositório,
build `pip install -r backend/requirements.txt` e comando acima.
**Pode ter cobrança separada da API**: some o preço mensal dos dois serviços,
banco, câmbio e impostos; o exemplo de R$ 38,50 da seção 3 cobre só a API.
Nada é contratado ou provisionado pelo código/blueprint. O teto de R$ 50
não é garantido. Não habilite outro serviço pago sem aprovação do custo.

**Alternativa sem novo serviço contratado:** em servidor que você já administra
e mantém ligado, use um processo supervisionado para API e outro para o worker.
Compartilham o mesmo PostgreSQL e timezone; não compartilham estado em memória.
Ou configure agendador do próprio servidor (por exemplo a cada minuto):

```powershell
python -m backend.worker_asaas --uma-vez --limite 100
```

Esse modo executa um lote, atualiza os indicadores e sai com código 0 se `pronto`,
1 em falha/alerta. Repetir o comando é seguro; atraso do agendador/servidor é
atraso de renovação. Não use a máquina da loja ou um PC desligável como scheduler.
Monitorar o processo é necessário: o log não notifica ninguém sozinho.

A primeira execução cria uma agenda imediata para cada assinatura do ambiente;
depois de sucesso, próxima conciliação em **6 horas**. Datas ficam no banco e
não reiniciam a contagem a cada deploy. Reexecuções recuperam webhook perdido
mesmo sem notificações novas. Falha de conciliação recebe o mesmo backoff;
todo o resultado daquela execução é transacional, sem licença parcial.

Em PostgreSQL, cada tarefa fica sob lock transacional `FOR UPDATE SKIP LOCKED`
enquanto consulta o Asaas; trabalhadores simultâneos não processam a mesma linha.
O vínculo da assinatura também é bloqueado para serializar cobranças da mesma
loja. Evento processado, cobrança, validade e conclusão do inbox são confirmados
juntos. Morte/interrupção libera locks e deixa a tarefa pendente para retomada;
nenhuma lease em memória precisa expirar. Em queda do banco, o erro persistido
pode não ser gravável: haverá log e batida atrasada quando a consulta voltar.
Uma falha com resultado de commit incerto pode levar a consulta remota repetida;
o resultado de licença/evento continua idempotente.

SQLite não oferece esses locks: serve a testes unitários/execução serial, não
ao deployment concorrente. Conciliação grande mantém uma transação/conexão
enquanto faz consultas (timeout de 10 segundos por chamada); acompanhe latência,
limites do Asaas e tamanho do pool. Não é fila de alto volume.

### Indicadores e alertas sem contratar notificações

`GET /v1/admin/cobrancas/operacao`, com `Authorization: Bearer` do
**`PDV_API_TOKEN`**, fornece JSON. Token de loja recebe 403; sem token, 401.
Não use `/v1/saude` como prova de saúde do worker: ela continua verificando só HTTP.

| Campo | Significado |
| --- | --- |
| `pronto` | `true` apenas sem alertas operacionais; não é aprovação comercial ou prova de licença |
| `alertas` | Códigos estáveis `worker_sem_batida`, `tarefas_com_erro`, `fila_atrasada`, `conciliacao_atrasada` |
| `worker_batida_em` | Última batida de algum worker; alerta após 5 minutos sem batida |
| `eventos_pendentes`, `evento_mais_antigo_em` | Inbox ainda não concluído, incluindo retentativas; alerta depois de 15 minutos |
| `tarefas_com_erro`, `tarefas_atrasadas` | Falhas consecutivas atuais e tarefas vencidas há mais de 15 minutos |
| `assinaturas_sem_conciliacao_recente` | Nunca conciliadas ou último sucesso há mais de 6 horas + 15 minutos |
| `ultimas_execucoes` | Até 50 tarefas recentes: última tentativa, fim, último sucesso, erro e próxima execução |
| `falhas`, `pendencias` | Até 50 falhas atuais e pendências mais antigas; contadores não se limitam a 50 |

O último erro e sua data ficam preservados mesmo depois da recuperação;
`falhas_seguidas=0` indica recuperação. Não é um histórico ilimitado por tentativa:
as colunas guardam a última execução/sucesso/erro de cada tarefa.
Logs `ALERTA_ASAAS`, `ALERTA_ASAAS_OPERACAO`, `ALERTA_ASAAS_WORKER` e
`ALERTA_ASAAS_INBOX` permitem coletar alertas existentes sem expor
credenciais/SQL/payloads. Um monitor seu pode consultar `pronto` periodicamente.
Não foi configurado envio de e-mail/SMS/WhatsApp, serviço pago ou monitor externo.
Se o worker morrer, ele próprio não pode emitir o alerta: monitore a batida via API.

As tabelas conservam inbox concluído e IDs de eventos para deduplicação.
Não há limpeza automática; dimensione banco/backups e defina retenção futura
antes de acumular alto volume. Ao restaurar backup, execute worker/conciliação
para recuperar o intervalo ausente. Não altere manualmente estados para ocultar erro.

### Cliente pagou, mas ainda não renovou

1. Confira ambiente e ID da assinatura.
2. Confira o estado da cobrança no Asaas; comprovante enviado por mensagem não
   substitui a confirmação do provedor.
3. Confira logs de webhook, resposta HTTP e estado do worker no endpoint admin.
4. Execute, no mesmo banco do servidor:

```powershell
python -m backend.lojas cobranca conciliar LOJA-CENTRO
python -m backend.lojas listar
```

5. Verifique conexão, token e consulta de licença no PDV.
6. Se for uma emergência legítima, emita uma licença excepcional no programa
   WillPDV Licenças; registre o motivo no seu atendimento.

A conciliação percorre todas as páginas de cobranças já geradas e consulta
também as cobranças que o nosso banco já conhecia. Ela pode ser executada de novo:
não soma meses. Não processa cobranças futuras ainda não geradas pelo Asaas.
No comando manual, se ocorrer falha no meio, pagamentos anteriores já conciliados
ficam persistidos; o comando retorna erro e pode ser repetido. No worker,
a conciliação completa de uma assinatura confirma ou reverte em uma transação.

Como rotina inicial, confira diariamente painel, indicadores, batida do worker e
alertas. A agenda persistente é executada pelo worker do servidor, não pelo PDV.
Instalação/supervisão do processo ou agendador **não são feitas automaticamente**.

### Erros frequentes

| Sintoma | Verificação |
| --- | --- |
| Webhook 401 | Segredo do webhook e cabeçalho corretos; não é API Key |
| Webhook 503 | Segredo não configurado ou banco/inbox indisponível; precisa reenviar |
| Webhook 422 | Formato/IDs inválidos ou mesmo evento com identificadores divergentes |
| Inbox em erro | Ver `ultimo_erro`: API indisponível, credenciais, valor, cliente, assinatura ou ambiente |
| Assinatura não vinculada | Evento fica em retentativa e alerta; vincule corretamente e concilie |
| `enfileirado` | Recebido com durabilidade; aguarde worker, não significa renovação concluída |
| `repetido` | Evento já persistido; resposta normal, não é nova mensalidade |
| Sem licença após vincular | Vincular não é pagar; confira recebimento |
| API de licença 403 | Token administrativo no lugar de token da loja, ou loja desativada |
| API de licença 404/409 | Sem período pago ou vencido; confira conciliação |
| API de licença 503 | Chave privada ausente/incorreta; confira correspondência com o PDV |
| Tudo certo no servidor, caixa antigo | Confira URL, token, rede e intervalo de 6 horas |
| Loja/token sumiram após deploy | Banco estava em disco efêmero; restaure backup e configure PostgreSQL |
| Fila Asaas pausada | Corrija o erro, reative no painel e concilie lojas afetadas |

Cobrança de assinatura desconhecida é recebida com 200 e fica em erro explícito
no worker, sem liberar loja; depois do vínculo, a retentativa/conciliação recupera
o estado. Pagamento avulso sem assinatura continua ignorado (`sem_assinatura`).
Se a conta tiver assinaturas de outros produtos, esses eventos também geram
pendências: restrinja o escopo do webhook/conta; não vincule uma loja indevida.

## 12. Backup, segurança e passagem para produção

Checklist antes da primeira loja real:

- [ ] Homologação completa aprovada no sandbox.
- [ ] Conta Asaas de produção regularizada e taxas conferidas.
- [ ] API sempre ligada, HTTPS e orçamento conferidos.
- [ ] Worker supervisionado ou scheduler do servidor ativo, custo aprovado e
      indicador `pronto=true` após conciliação inicial.
- [ ] PostgreSQL persistente, acesso restrito e conexão TLS.
- [ ] Banco de produção separado do banco sandbox.
- [ ] `ASAAS_AMBIENTE=producao`, API Key e webhook próprios de produção.
- [ ] Assinaturas e IDs criados em produção, não copiados do sandbox.
- [ ] Chave privada correta e cópia offline protegida.
- [ ] Backup do PostgreSQL, incluindo as tabelas Asaas, e restauração testada.
- [ ] Alertas de webhook enviados a um e-mail que você acompanha.
- [ ] Loja piloto real testada antes de cadastrar toda a carteira.
- [ ] Cliente informado sobre valor, recorrência, vencimento e carência.
- [ ] Procedimento para cancelamento, reembolso e suporte documentado no atendimento.

O backup deve incluir o banco completo da nuvem. Use a exportação/backup do
provedor ou `pg_dump` em ambiente administrativo com ferramentas PostgreSQL.
Guarde uma cópia criptografada fora do mesmo serviço e teste a restauração
em banco separado. A senha do banco e a chave privada precisam de proteção
própria; backup sem essas informações não garante recuperação do serviço.

Não publique a URL de conexão do banco. O PDV só acessa a API, nunca o PostgreSQL.
Os logs da integração não registram API Key, corpo completo de pagamento ou
dados pessoais. Os IDs de cobrança/assinatura são usados para diagnóstico.

Não foi instalado um serviço, comprado um domínio ou habilitada cobrança real.
Você decide quando contratar e quando mudar para produção.

## 13. Arquivos da implementação

| Arquivo | Responsabilidade |
| --- | --- |
| `backend/cobrancas.py` | Modelos, consultas Asaas, vínculo, período pago, eventos e conciliação |
| `backend/main.py` | Webhook autenticado, indicador administrativo e emissão existente da licença |
| `backend/operacao_asaas.py` | Inbox, agenda persistente, locks, backoff e indicadores |
| `backend/worker_asaas.py` | Entrada CLI do worker ou lote único do scheduler |
| `backend/lojas.py` | Comandos `cobranca vincular`, `cobranca listar`, `cobranca conciliar` |
| `src/sync/licenca_nuvem.py` | Cliente existente: busca e aplicação de licença assinada |
| `src/core/licenca.py` | Verificação offline, aviso, carência e bloqueio existentes |
| `tests/test_cobrancas_asaas.py` | Testes automatizados da integração, sem conta real |
| `tests/test_backend_operacao_asaas.py` | Operação em SQLite e concorrência/rollback/reinício PostgreSQL |
| `.github/workflows/testes.yml` | Suíte usual e service container PostgreSQL exclusivo de testes |

As consultas externas usam a biblioteca padrão Python. Não houve nova
dependência de produção e nenhuma chave do Asaas foi colocada no PDV.
Em PostgreSQL, a conciliação serializa atualizações por assinatura com bloqueio
transacional. SQLite é apenas para teste local, não para webhooks concorrentes
em produção.

## 14. Referências oficiais para estudar

- [Introdução às assinaturas Asaas](https://docs.asaas.com/docs/assinaturas)
- [Criar assinatura mensal](https://docs.asaas.com/docs/criando-uma-assinatura)
- [Introdução aos webhooks e autenticação](https://docs.asaas.com/docs/sobre-os-webhooks)
- [Eventos de cobranças](https://docs.asaas.com/docs/webhook-para-cobrancas)
- [Sandbox Asaas](https://docs.asaas.com/docs/sandbox)
- [Preços e taxas Asaas](https://www.asaas.com/precos-e-taxas)
- [Preços Render](https://render.com/pricing)
- [Limitações do Render gratuito](https://render.com/docs/free)
- [Planos Neon](https://neon.com/pricing)
- [Nuvem WillPDV](NUVEM.md)
- [Licenciador e chave de segurança](LICENCIADOR.md)
