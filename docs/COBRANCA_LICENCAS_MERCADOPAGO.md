# Cobrança da licença WillPDV com Mercado Pago

A mensalidade da licença é gerada por aqui (Pix e link de cartão/boleto). Quando o
Mercado Pago confirma o pagamento, a nuvem alonga a licença da loja e o caixa
busca o código assinado sozinho. O Asaas não faz mais parte deste repositório.

Nenhum segredo do Mercado Pago entra no git, no PDV ou neste guia. Os exemplos
abaixo são marcadores.

## O que você precisa configurar

1. Conta Mercado Pago com chave Pix (sem ela o Pix não é gerado).
2. Uma aplicação em [Suas integrações](https://www.mercadopago.com.br/developers/panel/app).
3. No servidor (Render ou o seu), só estas duas variáveis:
   - `MP_ACCESS_TOKEN` — Access Token da aplicação. O de teste começa com `TEST-`.
   - `MP_WEBHOOK_SECRET` — assinatura secreta gerada ao salvar o webhook.
4. Webhook de **Pagamentos** apontando para
   `https://SEU-SERVICO.onrender.com/v1/webhooks/mercadopago`.
5. O mesmo `MP_ACCESS_TOKEN` no terminal em que você roda `python -m backend.lojas cobranca`,
   junto com `PDV_NUVEM_DB_URL` do Neon. É esse comando que gera o Pix.
6. Para o e-mail da cobrança: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` e
   `SMTP_FROM`. No Gmail, host `smtp.gmail.com`, porta `587` e uma senha de app.
7. Se o bot de WhatsApp já está no ar: `WHATSAPP_API_URL` (https) e `WHATSAPP_API_TOKEN`.
   Sem os dois, a nuvem não envia mensagem; ela mostra um link `wa.me`.
8. Apague `ASAAS_AMBIENTE`, `ASAAS_API_KEY` e `ASAAS_WEBHOOK_TOKEN` se ainda existirem
   no painel. Não há mais worker (`backend.worker_asaas` foi removido).

O caixa continua só com a URL da nuvem, a chave da loja e o token da loja.
Não coloque o Access Token no PDV.

## Como funciona

```text
Você cadastra o plano da loja e gera a cobrança do mês
                         |
API cria um Pix (QR + copia e cola) e um link do Checkout Pro
                         |
Cliente paga Pix, cartão ou boleto
                         |
Mercado Pago avisa POST /v1/webhooks/mercadopago
                         |
A API confere x-signature e busca o pagamento de novo
                         |
Se estiver approved, com o valor certo, a loja fica paga até
um mês de calendário depois do vencimento daquela cobrança
                         |
O PDV busca a licença assinada (o mesmo fluxo de sempre)
```

- **Pix:** `POST /v1/payments` com `payment_method_id=pix`. A resposta traz o
  copia e cola (`qr_code`), o QR em base64 e uma página com o QR (`ticket_url`).
- **Cartão e boleto:** uma preferência do Checkout Pro. O Pix fica de fora desse
  link (`bank_transfer` excluído) para o cliente não pagar o mesmo mês duas vezes
  sem querer. Se mesmo assim os dois forem pagos, a licença não ganha dois meses:
  os dois pagamentos cobrem o mesmo vencimento. O Pix pendente é cancelado quando
  o outro meio é aprovado.
- **Não é débito automático.** Cada mês você gera a cobrança (ou o cliente paga
  o link daquele vencimento). O que é automático é a renovação da licença depois
  do pagamento aprovado.
- O corpo do webhook **não é comprovante**. Só o `data.id` da URL entra na
  assinatura. Em seguida a API faz `GET /v1/payments/{id}` e usa essa resposta.
- A mesma notificação (`x-request-id`) não é aplicada duas vezes. Outra
  notificação do mesmo pagamento (por exemplo o estorno) é aplicada de novo,
  sempre com o estado atual da API.
- Se o Mercado Pago estiver fora, a rota responde 503 e ele reenvia. Assinatura
  inválida responde 401. Pagamento que não é nosso responde 200 e não mexe na licença.

A varredura mora **dentro** do processo do Uvicorn (a cada 6 horas, e cerca de
20 segundos depois que o processo sobe). Não existe serviço worker. No Render
grátis o processo dorme: o webhook acorda o serviço; se a primeira tentativa
estourar o tempo do Mercado Pago (22 segundos, por causa do arranque frio), ele
tenta de novo a cada 15 minutos. Enquanto o processo está acordado, a varredura
relê as cobranças em aberto. Dá para forçar na hora com `cobranca conciliar`.

O banco da nuvem continua no Neon. A migração só cria tabelas novas
(`planos_mercadopago`, `cobrancas_mercadopago`, `pagamentos_mercadopago`,
`eventos_mercadopago`). `lojas.licenca_ate` não é alterada. Se ainda existir
tabela do Asaas, ela fica no banco e o código não usa mais.

## Quanto custa

O Mercado Pago cobra taxa por recebimento (Pix, cartão, boleto), não uma
mensalidade desta integração. Confira a taxa da sua conta antes de definir o
preço da licença. A nuvem em si continua no desenho do [NUVEM.md](NUVEM.md)
(Render + Neon). Esta cobrança não exige um segundo serviço pago.

## Segredos

| Variável | Onde | Para quê |
| --- | --- | --- |
| `MP_ACCESS_TOKEN` | Servidor e o terminal em que você gera a cobrança | Chamar a API |
| `MP_WEBHOOK_SECRET` | Servidor, igual à assinatura secreta do painel | Validar `x-signature` |
| `MP_BOLETO_METODO` | Servidor, opcional | Código do boleto; padrão `bolbradesco` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Servidor | E-mail da cobrança. No Gmail, `smtp.gmail.com`, porta `587` e senha de app |
| `WHATSAPP_API_URL`, `WHATSAPP_API_TOKEN` | Servidor, opcional | Bot que já recebe um POST. Sem os dois, fica o link `wa.me` |
| `PDV_NUVEM_DB_URL` | Servidor e o mesmo terminal | PostgreSQL (Neon) |
| `PDV_API_TOKEN` | Só você | Lista de lojas e `/v1/admin/cobrancas/operacao` |
| `PDV_LICENCA_CHAVE` | Servidor | Emitir a licença assinada (a chave que já existe) |

Não gere outro par de licença por causa desta troca: os caixas deixariam de
aceitar os códigos antigos.

`MP_VARREDURA=0` desliga a varredura interna (os testes usam isso). Em produção
deixe sem definir: com o Access Token presente, a varredura liga sozinha.
No Render, `RENDER_EXTERNAL_URL` já existe; se estiver preenchida com `https://`,
cada cobrança também manda `notification_url`. O webhook do painel continua
necessário.

Gere uma senha só se precisar de outro segredo seu (não é o caso destas duas
variáveis: elas saem do painel do Mercado Pago):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Preparar o servidor

O [NUVEM.md](NUVEM.md) sobe a API. Para esta cobrança, no serviço web:

1. Build: `pip install -r backend/requirements.txt`.
2. Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.
3. `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` no Environment do Render
   (`sync: false` no `render.yaml`: o valor não vai no git).
4. Comece pelo Access Token de **teste** (`TEST-`).
5. Publique e abra `https://SEU-SERVICO.onrender.com/v1/saude`
   (`{"status":"ok"}`). Isso não prova o Mercado Pago; só que a API subiu.
6. Na subida, as tabelas novas são criadas se faltarem. Faça backup do Neon antes.

No seu PC, para os comandos (o mesmo banco do servidor):

```powershell
$env:PDV_NUVEM_DB_URL = "postgresql://USUARIO:SENHA@HOST/BANCO?sslmode=require"
$env:MP_ACCESS_TOKEN = "COLE_FORA_DO_HISTORICO"
```

O `MP_WEBHOOK_SECRET` só precisa estar no servidor que recebe o webhook.

## Assinatura mensal (boleto + Pix)

Cada loja pode ter uma recorrência: valor em centavos, dia do mês (1 a 31; em
mês curto vale o último dia) e os contatos do responsável (e-mail e WhatsApp
`+55`). A varredura que já roda dentro da API gera a cobrança **5 dias antes**
do vencimento (dá para mudar com `--antecedencia`). Se o Render grátis estava
dormindo, ela ainda gera até 20 dias depois do vencimento, na primeira vez que
o processo acordar. O webhook que já existe renova a licença quando o boleto ou
o Pix fica `approved`.

O boleto do Mercado Pago exige, além do e-mail:

| Campo | Exemplo de formato |
| --- | --- |
| Nome completo | Nome e sobrenome |
| CPF ou CNPJ | com ou sem pontuação; o dígito é conferido |
| CEP | 8 dígitos |
| Logradouro, número, bairro, cidade | texto |
| UF | duas letras |

O padrão do meio é `bolbradesco`. Se a sua conta usar outro código de boleto,
defina `MP_BOLETO_METODO` (por exemplo `pec`). O Pix da mesma cobrança continua
sendo criado. O link de cartão (Checkout Pro) deixa de oferecer boleto e Pix,
para não haver duas vias do mesmo mês.

A loja precisa existir antes (`python -m backend.lojas criar CHAVE "Nome"`).
Não grave e-mail, telefone nem CPF no código: passe no comando ou no `curl`.

```powershell
python -m backend.lojas cobranca assinatura LOJA-CENTRO 24999 10 --email financeiro@exemplo.com --whatsapp "+55 11 98888-7777" --nome "Maria Silva" --documento 52998224725 --cep 01310100 --logradouro "Avenida Paulista" --numero 1000 --bairro "Bela Vista" --cidade "São Paulo" --uf SP
python -m backend.lojas cobranca emitir LOJA-CENTRO
python -m backend.lojas cobranca reenviar LOJA-CENTRO
python -m backend.lojas cobranca assinatura-parar LOJA-CENTRO
```

`24999` são R$ 249,99. `emitir` gera na hora se a data de hoje já está na janela;
senão não chama o Mercado Pago. `reenviar` manda de novo a cobrança atual.

Pelo navegador, com o `PDV_API_TOKEN`, sem precisar do PC ligado no banco:

```bash
curl -X POST https://SEU-SERVICO.onrender.com/v1/admin/cobrancas/assinatura \
  -H "Authorization: Bearer SEU_PDV_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"chave_loja\":\"LOJA-CENTRO\",\"valor_cent\":24999,\"dia_vencimento\":10,\"email\":\"financeiro@exemplo.com\",\"whatsapp\":\"+55 11 98888-7777\",\"nome\":\"Maria Silva\",\"documento\":\"52998224725\",\"cep\":\"01310100\",\"logradouro\":\"Avenida Paulista\",\"numero\":\"1000\",\"bairro\":\"Bela Vista\",\"cidade\":\"São Paulo\",\"uf\":\"SP\"}"
```

Para reenviar: `POST /v1/admin/cobrancas/reenviar` com `{"chave_loja":"LOJA-CENTRO"}`.
O mesmo token. Token de loja recebe 403.

### E-mail

Com as cinco variáveis `SMTP_*` preenchidas, cada cobrança nova sai em texto
simples: link do boleto (o PDF que o Mercado Pago devolve), linha digitável e
Pix copia e cola. Porta `465` usa SSL; qualquer outra (no Gmail, `587`) usa
STARTTLS. Senha de app do Gmail vai em `SMTP_PASSWORD`, nunca no git.
Se o SMTP não estiver configurado, a cobrança fica gravada e o aviso marca
`nao_configurado`. Depois de preencher o SMTP, rode `reenviar`.

### WhatsApp

Se `WHATSAPP_API_URL` (https) e `WHATSAPP_API_TOKEN` existirem, a nuvem faz:

```http
POST WHATSAPP_API_URL
Authorization: Bearer WHATSAPP_API_TOKEN
Content-Type: application/json

{"to": "+5511988887777", "text": "Licença WillPDV — ...\nBoleto (PDF): ...\nLinha digitável: ...\nPix copia e cola:\n..."}
```

O bot que você já hospeda no Render precisa aceitar esse JSON. Se ele espera
outro formato, coloque um adaptador na frente; a nuvem não fala o protocolo
interno de um fornecedor específico.

Sem essas variáveis, nada é postado. O comando, o `reenviar` e
`GET /v1/admin/cobrancas/operacao` incluem um link `https://wa.me/55...?...`
para você abrir e enviar na mão.

## Cadastrar a loja, o plano e a cobrança

Se a loja já existe, não recrie. Se for nova:

```powershell
python -m backend.lojas criar LOJA-CENTRO "Loja Centro"
```

Se ela já tem licença paga, grave a data **antes** do plano. Essa data vira o
piso (`validade_anterior`): um estorno não apaga o que já estava contratado.

```powershell
python -m backend.lojas assinatura LOJA-CENTRO 2026-11-15
python -m backend.lojas cobranca plano LOJA-CENTRO 9900 financeiro@loja.com
python -m backend.lojas cobranca gerar LOJA-CENTRO 2026-11-15
python -m backend.lojas cobranca listar
```

`9900` são centavos: R$ 99,00. O e-mail é o do pagador; o Mercado Pago exige
e-mail para criar o Pix. No teste, use o e-mail do usuário de teste da sua conta.

O `gerar` imprime:

- o **Pix copia e cola**;
- a **página do QR** (abre o QR Code);
- o **link** do Checkout Pro (cartão ou boleto). No token `TEST-` o link é o de
  sandbox.

Mande isso ao cliente pelo canal que você já usa. Não há botão de pagamento no PDV.
O QR em base64 fica gravado na cobrança; o copia e cola é o que o cliente cola no banco.

Rodar `gerar` de novo no mesmo vencimento não cria outra cobrança: devolve a mesma.
O vencimento é a data daquela mensalidade. A licença vai até um mês de calendário
depois **dessa data**, não até um mês depois do dia em que o webhook chegou.
O Pix do Mercado Pago expira no máximo em 30 dias; se o vencimento for mais longe,
o código Pix vale 30 dias a partir da geração, mas o período da licença continua
sendo o do vencimento.

Depois do plano, `python -m backend.lojas assinatura LOJA ...` é recusado, para
não haver duas datas mandando. Liberação excepcional: código no WillPDV Licenças.

`plano` de novo só troca valor e e-mail das próximas cobranças. Não reescreve o piso.

## Webhook no painel do Mercado Pago

Webhook é o Mercado Pago chamando a nossa API. Não é a página em que o cliente paga.
Não use IPN; use Webhooks.

1. Abra [Suas integrações](https://www.mercadopago.com.br/developers/panel/app)
   e escolha a aplicação (crie uma se ainda não existir).
2. No menu da esquerda: **Webhooks > Configurar notificações**.
3. **URL modo teste** e **URL modo produção** (pode ser o mesmo caminho; o que muda
   é o Access Token do servidor):

   `https://SEU-SERVICO.onrender.com/v1/webhooks/mercadopago`

   Sem barra no final e sem query string. O Mercado Pago acrescenta `data.id` e `type`.
4. Evento: **Pagamentos** (tópico `payment`), formato JSON.
5. Salve. O painel mostra a **assinatura secreta**. Copie para `MP_WEBHOOK_SECRET`
   no Render e faça o deploy pegar o valor novo. Se você redefinir a assinatura no
   painel, atualize a variável.
6. Em **Credenciais**, copie o Access Token de teste ou o de produção para
   `MP_ACCESS_TOKEN`. Teste e produção não se misturam: token `TEST-` só vê
   pagamento de teste.
7. O relógio do servidor precisa estar certo. A assinatura expira em 5 minutos
   (`ts` do cabeçalho `x-signature`). Cada reenvio do Mercado Pago traz `ts` novo.

A conferência segue o modelo publicado pelo Mercado Pago, sem SDK (a biblioteca
padrão basta; não há dependência nova):

```text
id:<data.id em minúsculas>;request-id:<x-request-id>;ts:<ts>;
HMAC-SHA256 com MP_WEBHOOK_SECRET, comparado ao v1 em tempo constante
```

O `data.id` usado é o da URL, não o do JSON. Depois da assinatura válida, a API
busca o pagamento. Status que liberam: `approved`, moeda BRL, valor igual ao da
cobrança, sem estorno (`transaction_amount_refunded` zerado) e, se o pagamento
trouxer `metadata.chave_loja`, a loja tem de ser a do plano.

`pending`, `in_process`, `rejected`, `cancelled`, `refunded` e `charged_back`
não liberam. Estorno ou chargeback tira a contribuição daquela cobrança; ficam
as outras cobranças pagas e a validade anterior ao plano.

No painel de notificações dá para ver entrega com sucesso ou falha. HTTP 200 com
`situacao=processado` quer dizer que a API conferiu o pagamento, não que o caixa
já mostrou a licença nova (o PDV consulta no máximo a cada 6 horas; na entrada
bloqueada, tenta na hora).

| Resposta | Significado |
| --- | --- |
| 200 `processado` | Pagamento nosso conferido na API |
| 200 `repetido` | Esse `x-request-id` já tinha sido aplicado |
| 200 `desconhecida` | Pagamento sem cobrança nossa; nada é liberado |
| 200 `ignorado` | Não é tópico `payment` |
| 401 | Assinatura ausente, errada ou velha |
| 503 | Segredo faltando, ou a API do Mercado Pago não respondeu (ele deve reenviar) |

`GET /v1/admin/cobrancas/operacao` com `Authorization: Bearer` do **`PDV_API_TOKEN`**
lista situação, vencimento e se há Pix/link, sem copia e cola, sem e-mail e sem
token. Token de loja recebe 403.

## Regras da validade

| Vencimento da cobrança | Licença daquela cobrança |
| --- | --- |
| 15/10/2026 | 15/11/2026 |
| 31/01/2026 | 28/02/2026 |
| 31/01/2028 | 29/02/2028 |
| 31/12/2026 | 31/01/2027 |

Vale a maior data entre as cobranças pagas e a validade anterior. Pagar de novo
o mesmo vencimento não soma outro mês. Uma cobrança antiga não encurta uma mais
nova. Uma licença já entregue ao caixa é um documento offline: o estorno corta a
data no servidor, mas o código que o PDV já guardou vale até o prazo dele.

Loja desativada não recebe licença nova, mesmo com pagamento aprovado.

## Testar sem dinheiro real

Usuários e credenciais de teste, no painel do Mercado Pago. Não pague um Pix de
teste com dinheiro real.

```powershell
python -m pip install -r backend\requirements.txt httpx
python -m unittest tests.test_cobrancas_mercadopago tests.test_licenca_nuvem tests.test_nuvem tests.test_licenca
```

Os testes simulam a API. Não usam token real. No CI, o job
`Mercado Pago / PostgreSQL 16` também cobre duas notificações ao mesmo tempo no
PostgreSQL (`PDV_TESTE_NUVEM_DB_URL`). Não aponte essa variável para o banco de
produção: o teste apaga as tabelas de loja e de cobrança daquele banco.

Homologação na conta de teste:

1. Suba a API com token `TEST-` e o segredo do webhook de teste.
2. Crie a loja, o plano e uma cobrança. Confira que a data da loja não andou.
3. Pague com o usuário de teste (Pix de teste ou o link sandbox).
4. Veja HTTP 200 no painel de notificações.
5. `python -m backend.lojas listar` deve mostrar a data nova.
6. `python -m backend.lojas cobranca conciliar LOJA-TESTE` não soma outro mês.
7. Ligue um PDV de teste e confirme a licença. Sem rede, o código já recebido continua.
8. Um segredo errado tem de responder 401 e não renovar.

## Cliente pagou e a licença não andou

1. Confira se o token do servidor é do mesmo modo (teste ou produção) do pagamento.
2. Confira o pagamento no painel do Mercado Pago. Comprovante de mensagem não substitui a API.
3. Veja o histórico do webhook (401, 503, 200).
4. No PC, com o banco do servidor e o Access Token:

```powershell
python -m backend.lojas cobranca conciliar LOJA-CENTRO
python -m backend.lojas listar
```

5. No caixa: URL, token da loja e a consulta de licença (até 6 horas, ou na entrada bloqueada).
6. Emergência: emita um código no WillPDV Licenças e anote o motivo. Isso não passa
   pelo plano; se a loja já tem plano, a data do servidor continua vindo dos pagamentos.

## Produção

- [ ] Homologação feita com token de teste.
- [ ] Access Token de **produção** no servidor e no terminal de `gerar` (sem `TEST-`).
- [ ] Webhook de produção salvo e `MP_WEBHOOK_SECRET` igual à assinatura secreta.
- [ ] Chave Pix da conta de produção ativa.
- [ ] Banco de produção separado do banco em que você testou.
- [ ] Backup do Neon restaurado uma vez em banco à parte.
- [ ] Chave privada da licença é a mesma dos PDVs.
- [ ] Variáveis `ASAAS_*` removidas.
- [ ] Uma loja piloto antes do restante.
- [ ] Cliente informado do valor, do vencimento e de que pagar não libera o caixa
      se ele estiver sem internet (precisa buscar a licença, ou receber um código manual).

Não foi criada conta, domínio nem cobrança real por este trabalho. Você decide
quando trocar o token de teste pelo de produção.

## Arquivos

| Arquivo | Função |
| --- | --- |
| `backend/cobranca_mercadopago.py` | Plano, Pix, Checkout Pro, assinatura do webhook, renovação e varredura |
| `backend/main.py` | Webhook, `POST /v1/admin/cobrancas/assinatura`, `POST /v1/admin/cobrancas/reenviar` e o resumo em `/v1/admin/cobrancas/operacao` |
| `backend/lojas.py` | `cobranca plano`, `gerar`, `listar`, `conciliar` |
| `render.yaml` | `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` sem valor no git |
| `tests/test_cobrancas_mercadopago.py` | Testes sem conta real |
| `src/sync/licenca_nuvem.py` | O caixa busca a licença assinada, como antes |
| `src/core/licenca.py` | Conferência offline, aviso e carência, como antes |

## Referências

- [Webhooks e assinatura x-signature](https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks)
- [Pix na API de pagamentos](https://www.mercadopago.com.br/developers/pt/docs/checkout-api-payments/integration-configuration/integrate-pix)
- [Checkout Pro](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/overview)
- [Credenciais](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/additional-content/your-integrations/credentials)
- [Suas integrações](https://www.mercadopago.com.br/developers/panel/app)
- [Nuvem WillPDV](NUVEM.md)
