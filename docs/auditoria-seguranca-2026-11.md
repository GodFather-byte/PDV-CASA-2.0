# Auditoria de segurança — WillPDV — 24/11/2026

Leitura do repositório e consulta pública aos endereços que já estão no ar
(`https://willpdv.com.br` e o serviço da nuvem no Render). Não houve mudança de
código, teste de pagamento de verdade, tentativa de entrar em loja nem leitura
de valor de segredo. Onde um segredo aparece no código ou no git, o relatório
cita arquivo, linha ou commit e o tipo. O valor não entra aqui.

Escopo pedido: login e sessões do painel, chaves de loja e terminais, redes
(`?grupo=`), API do assistente (`/v1/painel/gestao/`), gerente e operador,
força bruta, IDOR, webhooks do Mercado Pago, segredos, injeção, XSS, CSRF,
planilha, cabeçalhos, dependências, programa do caixa, LGPD e GitHub Actions.

## Como foi feito

- Leitura do código da nuvem (`backend/`), do caixa (`src/`), dos workflows
  (`.github/workflows/`) e do `render.yaml`.
- Varredura dos 534 commits em busca de chave privada, token de GitHub, chave
  de AWS, token real do Mercado Pago e URL de banco com senha. O que sobrou
  eram exemplos de documentação e de teste.
- `pip-audit` (base OSV/PyPI) em `backend/requirements.txt`, `requirements.txt`,
  `requirements-test.txt` e `requirements-build.txt`, em 24/11/2026. Não há
  `package.json`; `npm audit` não se aplica.
- Consulta pública, sem credencial: cabeçalhos, `/docs`, `/openapi.json`,
  `/painel/` e os dois webhooks sem o cabeçalho `x-signature`.

## O que já está bem fechado

Isto não é pendência. Serve para não “corrigir” o que já funciona.

- **Mensalidade.** `POST /v1/webhooks/mercadopago` exige `x-signature`
  (`backend/cobranca_mercadopago.py`, por volta da linha 235). O HMAC cobre o
  id, o `x-request-id` e o `ts`, com prazo de 5 minutos. O corpo não é
  comprovante: a nuvem busca o pagamento na API do Mercado Pago e só renova a
  licença se o status for aprovado, o valor em centavos for o da cobrança, a
  moeda for BRL e a referência for a daquela cobrança. Reenvio com o mesmo
  `x-request-id` não repete. Sem o segredo, a rota responde 503, não libera.
- **Site, hoje.** `GET` e `POST` em `/v1/pagamentos/webhook` sem assinatura
  responderam **401** (“Assinatura do webhook inválida.”) em 24/11/2026, no
  domínio público. O mesmo 401 veio do webhook das mensalidades no host do
  Render. O segredo está ligado nos dois. O site, quando a assinatura confere,
  também busca o pagamento na API, exige BRL e o valor exato do plano e não
  duplica o mesmo id (`backend/site_checkout.py`). Esse webhook não emite licença.
- **Token de loja.** A nuvem guarda só o SHA-256. A senha do painel usa
  PBKDF2-SHA256 com sal (310 mil voltas). A senha do operador no caixa usa
  PBKDF2 com 600 mil voltas. A comparação usa `hmac.compare_digest`.
- **Loja de outra pessoa.** Nas rotas de gestão e de importação, o parâmetro
  `loja` só vale se for a loja da sessão, a loja do token `wpdv_` ou uma loja
  da mesma rede. Entrar numa loja da rede (`POST /v1/painel/grupo/entrar`)
  confere `grupo_id`. Juntar outra loja no painel pede a senha do painel dela.
  Não achei um caminho em que a sessão da loja A leia venda, estoque ou backup
  da loja B.
- **Central do fornecedor.** Cookie `HttpOnly`, `Secure` fora do localhost,
  `SameSite=Strict`, CSRF no POST, e os cabeçalhos CSP, `X-Frame-Options: DENY`,
  `nosniff` e `Referrer-Policy` nas rotas `/central` e `/v1/fornecedor`.
  Conferido ao vivo no host do Render.
- **Atualização do caixa.** O manifesto é assinado com Ed25519 (a chave pública
  vai no programa; a semente fica no segredo do GitHub). O arquivo só substitui
  o download se o tamanho e o SHA-256 baterem com o manifesto. A tarefa do
  Windows confere de novo antes de instalar.
- **Caixas da mesma loja.** O canal entre o caixa principal e o adicional usa
  ChaCha20-Poly1305 com chave de pareamento.
- **Redirect do site.** O 301 do host `*.onrender.com` para
  `https://willpdv.com.br` só vale para uma lista fechada de páginas públicas
  (`backend/site.py`, `PAGINAS_PUBLICAS`). A consulta é conservada, sem mudar o
  destino. Não é open redirect. `/v1`, painel, webhook e `/health` não entram.
- **SQL.** Valores de filtro vão como parâmetro. O nome da tabela do espelho
  sai da lista de cadastros do código, não de um texto livre da internet.
- **CI.** Não há `pull_request_target`. O workflow de testes pede só
  `contents: read`. O hook de deploy do Render não é impresso; o log mostra o
  código HTTP. As dependências Python estão com hash.
- **Git.** Nenhum `.env`, nenhuma chave PEM e nenhum token real de GitHub, AWS
  ou Mercado Pago nos 534 commits. As ocorrências de `APP_USR-` são textos de
  teste (`ficticio`, um token curto de teste do Pix). As URLs `postgresql://`
  do histórico são exemplo de documentação ou `u:p@h` de teste.

## Achados

A severidade é o estrago se alguém de fora, ou alguém que já tenha a central,
usar o que está descrito. “Como explorar” é o caminho em linguagem simples, não
um roteiro para repetir.

### C1 — Crítica — O backup na nuvem leva o token do Pix da loja

**Onde.** O caixa copia o banco inteiro (`src/controllers/utilitario_controller.py`,
`backup`) e a nuvem guarda esse arquivo em gzip no Postgres
(`backend/backup_nuvem.py`, envio em `POST /v1/backup` e download em
`GET /v1/backup/{id}` e `GET /v1/fornecedor/lojas/{chave}/backups/{id}`).
No mesmo banco ficam, em texto puro, `pix_mp_token` (Access Token de produção
do Mercado Pago da loja; `src/database/sementes.py` linha 101 e
`src/controllers/config_controller.py` linha 141) e `nfce_certificado_senha`
(`sementes.py` linha 96, `config_controller.py` linha 151), além de
`api_token`, clientes, vendas e a ficha dos hóspedes.

O backup externo para pasta sincronizada é cifrado (`src/core/backup_seguro.py`).
O que sobe para a nuvem não é.

**Como explorar.** Quem baixa o backup abre o SQLite e lê o Access Token do
Pix. Com esse token a API do Mercado Pago da loja cria e consulta cobrança:
o dinheiro cai na conta Mercado Pago da loja, e quem tem o token fala com essa
conta. A central do fornecedor já baixa qualquer loja (fica na auditoria, mas
o arquivo sai inteiro). O mesmo acontece para quem ler o Postgres da nuvem
(Neon) ou para quem roubar o token da loja e chamar `GET /v1/backup/{id}`.

**Correção.** Antes de enviar, gravar uma cópia sem as chaves de segredo
(`pix_mp_token`, `nfce_certificado_senha`, `api_token`, senhas e o cofre do
backup), ou cifrar o arquivo com uma senha que não fica no Postgres. A central
não precisa receber o token do Pix para restaurar cadastro e venda. Na
restauração, as chaves desta instalação já são preservadas de propósito
(`src/sync/backup_nuvem.py`, `CHAVES_DA_INSTALACAO`): o problema é o que fica
guardado na nuvem, não o que volta para o caixa novo.

### A1 — Alta — `/docs` público no mesmo site do painel

**Onde.** `backend/main.py` linha 126 cria o FastAPI sem desligar a
documentação. Em 24/11/2026, `https://willpdv.com.br/docs` e
`/openapi.json` no host do Render responderam 200. A página puxa o Swagger de
`cdn.jsdelivr.net`, sem integridade. O painel também abre em
`https://willpdv.com.br/painel/` (200). O token da sessão fica no
`localStorage` (`backend/painel_web/app.js`).

**Como explorar.** A lista de rotas da API, inclusive as de administrador,
fica na internet. Pior: site, painel e `/docs` são o mesmo domínio. Um script
que rode nessa origem lê o token de quem já entrou no painel e usa a sessão
por até 30 dias. O JavaScript do `/docs` é de um terceiro. Um link para
`/docs` aberto por quem está logado executa esse script no site do painel.

**Correção.** Em produção, `docs_url=None`, `redoc_url=None` e
`openapi_url=None`. Não carregar script de CDN na origem do painel. Ver também
A2 (cabeçalhos) e M4 (onde o token mora).

### A2 — Alta — O caixa aceita nuvem em HTTP

**Onde.** Licença, painel, backup, cardápio e sincronização usam o `api_url`
gravado na configuração e mandam `Authorization: Bearer` com o token da loja
(`src/sync/licenca_nuvem.py`, `src/sync/painel_envio.py`,
`src/sync/sincronizador.py`). Só a ponte do fornecedor exige HTTPS, com HTTP
apenas em localhost (`src/sync/ponte.py`, `url_segura`, por volta da linha 117).
O download da atualização também aceita `http://` se o endereço do manifesto
for absoluto (`src/atualizacao/cliente.py`, `url_absoluta`). O SHA-256 impede
trocar o executável no caminho, mas não impede apontar o `api_url` para um
servidor sem TLS.

**Como explorar.** Se o endereço da nuvem for `http://`, ou se alguém alterar
esse campo nas configurações do caixa, o token da loja, as vendas e o backup
passam em claro na rede. Quem estiver no meio (Wi-Fi da loja, um proxy)
copia o token e passa a falar com a nuvem como aquele caixa.

**Correção.** A mesma regra da ponte em todo envio: só `https`, HTTP só em
localhost. Recusar gravar outro endereço. No manifesto, aceitar download só
de `https` e de um host conhecido (GitHub de downloads ou a própria nuvem).

### A3 — Alta — Pillow 12.3.0 abre foto que veio de fora

**Onde.** `requirements.txt`, `pillow==12.3.0`. O `pip-audit` de 24/11/2026
apontou 42 avisos, com correção em 13.0.0. Vários são leitura ou escrita fora
da memória em JPEG, PNG e BMP (por exemplo CVE-2026-112396, CVE-2026-96638,
CVE-2026-96778). A nuvem (`backend/requirements.txt`) não depende do Pillow.
O caixa abre logo e foto de produto só em PNG, JPEG, BMP e WEBP, com teto de
tamanho e aviso de imagem bomba (`src/core/identidade_visual.py`,
`src/controllers/foto_produto_controller.py`). Isso corta TIFF, WMF e EPS.
Não corta falha dentro do JPEG, do PNG ou do BMP.

**Como explorar.** Uma foto que o operador importa, ou uma imagem que o caixa
baixa por HTTPS ao buscar o produto pelo código de barras, passa pelo
decodificador. Uma imagem feita para acertar esses avisos pode travar o caixa
ou, nas falhas de escrita na memória, executar código no Windows da loja.

**Correção.** Subir o Pillow para 13.0.0 (ou a versão que o aviso indicar na
hora do upgrade) e manter a lista de formatos. Não decodificar o arquivo
baixado da internet sem o teto que já existe.

### A4 — Alta — A central trava com oito tentativas, e o IP não é o do cliente

**Onde.** `backend/central_fornecedor.py`, login por volta das linhas 260–277.
Cada chamada entra na fila do IP **antes** de conferir a senha, e um acerto
não tira o IP da fila. O `render.yaml` sobe o uvicorn sem `--proxy-headers`
(linha 14). Atrás do Render, `request.client.host` tende a ser o proxy, o
mesmo para todo mundo. O painel do dono trava por nome de loja, não por IP
(ver M2).

**Como explorar.** Oito senhas erradas na central, de qualquer lugar, enchem
a fila daquele IP. Se todas as visitas aparecem com o IP do proxy, o
fornecedor também fica de fora por 15 minutos. Oito entradas certas seguidas
do mesmo IP fazem a mesma trava, porque o acerto não zera o contador. A
central é quem cria loja, token e baixa o backup do item C1.

**Correção.** Contar só senha errada e zerar no acerto. Ler o IP do cliente
só se o proxy for o do Render (`--proxy-headers` com a faixa de IPs dele, sem
confiar no primeiro valor que o visitante mandar). Limite separado para não
misturar o fornecedor com o resto do mundo.

### M1 — Média — O webhook do site fica opcional se o segredo sumir

**Onde.** `backend/site_checkout.py`, `processar_webhook`, por volta das
linhas 396–409. Se `MP_WEBHOOK_SECRET` estiver vazio, a rota não exige
assinatura: pega o id da URL e consulta a API. O webhook das mensalidades, no
mesmo segredo, responde 503 e não segue (`backend/main.py`, por volta da
linha 179). O `render.yaml` declara a variável com `sync: false` (não vem
preenchida do arquivo).

**Como explorar.** Hoje não dá: os dois endereços responderam 401 sem
assinatura, então o segredo está presente. Se alguém apagar a variável no
Render, o site passa a aceitar aviso sem assinatura. Ainda assim o código
confere valor, moeda e referência na API, e não dá para inventar um pagamento
pago. O furo é a trava deixar de existir sem o serviço recusar. Dá também
para disparar consulta à API do Mercado Pago à vontade.

**Correção.** Fazer como a mensalidade: sem segredo, 503 e não gravar. Não
tratar “segredo vazio” como modo permitido.

### M2 — Média — Força bruta no painel trava a loja, e a senha da rede não segura a API

**Onde.** `backend/painel.py`: 8 erros em 15 minutos por nome de loja
(`TENTATIVAS_LOGIN`, `JANELA_LOGIN_SEG`), na memória do processo. Com 500
chaves na memória, loja nova também é recusada (`bloqueada`). A sessão dura
30 dias. A rede com senha temporária bloqueia o resumo e o “entrar na loja”
(`_rede`, por volta da linha 1293) enquanto `deve_trocar_senha` for verdade.
`backend/gestao_painel.py` (`acesso` / `loja_de`, por volta das linhas 820–864)
e `backend/importacao_painel.py` não olham essa flag.

**Como explorar.** Oito senhas erradas em `EA-SUPERACOES2` impedem o dono
dessa loja de entrar por 15 minutos. Quinhentos nomes diferentes travam o
login de todo o painel até a janela passar. Um restart do Render zera a
contagem. A senha escolhida pelo dono pode ter 8 caracteres quaisquer, sem
variedade: 8 tentativas a cada 15 minutos ainda cabe um dicionário lento, loja
por loja. Quem recebeu a senha temporária da rede (`/painel/?grupo=`) e ainda
não trocou consegue chamar `/v1/painel/gestao/` e a importação, escolher a
loja da rede e mudar preço e estoque. A tela pede a troca; a API não pede.

Não há papel de operador na nuvem. No caixa, o nível vai de 0 a 4 e a senha
de supervisor fica no computador. No painel, a senha do dono e o token
`wpdv_` fazem o mesmo serviço de dono (preço, estoque, planilha). Isso está
escrito em `docs/api-assistente.md`.

**Correção.** Limite por IP e por loja, sem travar as outras lojas quando a
memória enche. Não usar a trava como negação de serviço do dono (atraso
crescente, aviso). Exigir `deve_trocar_senha` em toda rota da rede, inclusive
gestão e importação. Subir o piso da senha que o dono escolhe.

### M3 — Média — Token `wpdv_` não vence

**Onde.** `backend/importacao_painel.py`, `novo_token`. Até 5 tokens por loja,
guardados como hash, mostrados uma vez. Não têm data de fim. Servem na gestão
e na importação com o mesmo poder da sessão do dono. Não criam outro token.

**Como explorar.** Um token copiado (assistente, print, planilha compartilhada)
continua alterando preço e estoque até alguém revogar na tela. Não expira
sozinho.

**Correção.** Prazo curto, revogação já existe, e deixar claro na tela a data
do último uso (o campo já é gravado).

### M4 — Média — Sessão de 30 dias no navegador, sem os cabeçalhos do site

**Onde.** `backend/painel.py`, `DIAS_SESSAO = 30` e `abrir_sessao`. O app guarda
o bearer no `localStorage`, não em cookie. Por isso não há CSRF clássico: outro
site não manda esse cabeçalho sozinho. Em 24/11/2026 o `GET` de
`https://willpdv.com.br/painel/` trouxe `Cache-Control: no-cache` e não trouxe
`Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`,
`X-Content-Type-Options` nem `Referrer-Policy`. A home do domínio também não
trouxe HSTS. O HTTP do domínio redireciona para HTTPS pelo Cloudflare (301),
sem o cabeçalho que fixa isso no navegador. A central, no mesmo serviço, tem
esses cabeçalhos.

**Como explorar.** Qualquer script que rode em `willpdv.com.br` (o `/docs` do
item A1, ou uma falha nova no site) lê o token e usa a sessão por até 30 dias,
mesmo depois que o dono fechou a aba. Sem `frame-ancestors`, outra página pode
embeber o painel e induzir clique. Sem HSTS, a primeira visita ainda pode ser
desviada antes do redirect.

**Correção.** Os mesmos cabeçalhos da central em todo o serviço, HSTS no
Cloudflare, e a sessão do painel em cookie `HttpOnly` + `Secure` +
`SameSite=Strict`, com prazo menor e CSRF como o da central.

### M5 — Média — Teste grátis entrega token e a trava por IP não vê o cliente

**Onde.** `backend/site_teste.py`. O `POST /v1/site/teste` cria loja de verdade,
devolve senha do painel e código de instalação (esse código leva o token da
loja). Teto de 30 por dia e 3 por IP, mas o IP é `request.client.host` (o
mesmo limite do item A4). O sal do hash do WhatsApp cai em `willpdv-site` se
`PDV_SITE_SAL` não estiver definido. O WhatsApp também fica em claro, para o
fornecedor ligar. Há campo-isca e um teste por WhatsApp.

**Como explorar.** Com o serviço atrás do proxy, o “3 por IP” não separa as
pessoas. Dá para abrir até 30 lojas por dia, cada uma com token e senha na
resposta. Não invade loja que já existe. Abre loja nova e gasta a cota.

**Correção.** IP real só via proxy confiável. Sal próprio no ambiente.
Desligar com `PDV_SITE_TESTE=0` quando não houver campanha. Não registrar o
token em log.

### M6 — Média — Planilha: zip pequeno pode descompactar demais

**Onde.** `src/controllers/importacao_produtos.py`, `_ler_xlsx`. O envio para
em 3 MB (`LIMITE_PLANILHA_BYTES` em `backend/retaguarda.py`). O XML é lido com
`ElementTree`, que não busca entidade externa (não é o XXE clássico), mas
`ZipFile.read` não limita o tamanho descompactado. A exportação CSV
(`csv_produtos` em `backend/importacao_painel.py`) não marca célula que começa
com `=`, `+`, `-` ou `@`. Macro de `.xlsm` não é executada: o código só lê a
primeira folha.

**Como explorar.** Um `.xlsx` de poucos MB que explode ao descompactar ocupa a
memória do serviço no Render. Um nome de produto que começa com `=` vira
fórmula se o dono abrir o CSV no Excel.

**Correção.** Teto de bytes descompactados e de tamanho do XML antes do parse.
Na exportação, prefixar a célula perigosa.

### M7 — Média — Senha de operador de 1 a 10, sem diferença de maiúscula

**Onde.** `src/core/seguranca.py` (`FORMATO_SENHA`) e
`src/controllers/acesso_controller.py` (por volta da linha 66): “de 1 a 10
letras ou números”, comparadas em maiúsculas. Cinco erros travam aquele
usuário por 5 minutos, e o contador fica no banco. O hash é forte. A senha
não sobe no espelho da retaguarda (campo do tipo senha é omitido).

**Como explorar.** No computador da loja, a senha `1` é aceita para um
operador. Não é um ataque pela internet. Quem senta no caixa, ou quem já está
na rede dos caixas adicionais, não precisa de uma senha longa.

**Correção.** Mínimo maior para gerente (nível alto), e parar de igualar
maiúscula e minúscula se o dono aceitar mudar a regra do manual.

### M8 — Média — Dados pessoais na nuvem, sem prazo nem pedido de apagar

**Onde.**

- Com a retaguarda ligada, o espelho sobe o cadastro de clientes com CPF e
  telefone (`src/controllers/entidades.py`, campo `cpf`;
  `src/controllers/retaguarda_controller.py`, `linhas`). Configuração marcada
  como segredo e a seção Integrações não sobem. A senha de operador não sobe.
- O painel guarda a venda por 120 dias (`RETENCAO_VENDAS_DIAS` em
  `backend/painel.py`), com o nome do cliente no texto de entrega e de
  caderneta (`src/sync/painel_envio.py`).
- O backup do item C1 leva a ficha do hotel (CPF, documento, nascimento;
  `src/controllers/hotel_controller.py`, `CAMPOS_HOSPEDE`). O código da ficha
  diz que nada é enviado ao Ministério do Turismo. O backup da nuvem é outro
  caminho e leva o banco inteiro.
- Checkout do site (`site_pedidos`: nome, e-mail, WhatsApp, nome da loja) e
  pedido do cardápio (nome, telefone, endereço) não têm a limpeza dos 120 dias.
- Não há rota para o titular pedir exclusão ou uma cópia só dos dados dele.

**Como explorar.** Não é uma invasão por si. É o que sai junto se o Postgres
vazar, se a central baixar o backup, ou se a sessão do painel for copiada
(itens A1 e M4). CPF de cliente e de hóspede não deveria estar no mesmo balde
que o token do Pix.

**Correção.** Não espelhar CPF se a tela da retaguarda não precisa dele.
Prazo para pedido online, checkout e teste grátis. Cifrar o backup (C1).
Um caminho documentado para apagar os dados de uma pessoa quando ela pedir.

### M9 — Média — `cryptography` 46.0.7 no caixa e no build

**Onde.** `requirements.txt` e `requirements-build.txt`, `cryptography==46.0.7`.
O `pip-audit` de 24/11/2026 apontou os avisos PYSEC-2026-3554, PYSEC-2026-3552,
PYSEC-2026-3553 e GHSA-537c-gmf6-5ccf. As correções indicadas vão de 48.0.1 a
50.0.0, conforme o aviso: curinga de certificado que foge da restrição de um
CA, diferença de tempo ao decifrar PKCS#7 e OpenSSL embutido na roda antigo.
A nuvem (`backend/requirements.txt`) não depende desse pacote. O caixa usa a
biblioteca na rede dos terminais (`src/database/rede.py`), no certificado A1
da NFC-e (`src/fiscal/sefaz/assinatura.py`) e no backup cifrado
(`src/core/backup_seguro.py`). O HTTPS do caixa para a nuvem passa pelo
`requests`, não por esse verificador.

**Como explorar.** Não é o mesmo caminho de uma foto maliciosa. O risco é a
biblioteca que assina a nota, abre o certificado e cifra a rede dos caixas
estar atrás de avisos já publicados. Quem monta um certificado ou um PKCS#7
para o código que verifica cadeia com essa versão pode se aproveitar do que
o aviso descreve.

**Correção.** Subir para a versão que cobre os quatro avisos (a mais nova
entre as indicadas, hoje 50.0.0) e rodar de novo o `pip-audit`.

### M10 — Média — Pull request pode rodar no PC do dono

**Onde.** `.github/workflows/testes.yml`. Em repositório privado, com a
variável `RUNNER_PC`, a suíte do `pull_request` usa o computador do dono. O
próprio comentário do arquivo diz que em repositório público esse PC não entra.
Não há `pull_request_target`. O job de teste não recebe
`PDV_ATUALIZACAO_CHAVE` nem `PDV_API_TOKEN`. Os workflows que publicam pacote
(`publicar-pacote.yml`, chamado pelo build e pelas edições) são
`workflow_dispatch` / `workflow_call`, com `contents: write` e a chave de
assinatura. Isso é esperado para publicar, e não dispara em pull request.

**Como explorar.** Quem abre um pull request no repositório privado faz o PC
do dono executar o código daquele PR (a suíte importa o que está no branch).
Não recebe os segredos do GitHub Actions. Recebe o que estiver no disco
daquele PC: bancos de loja, chaves locais, sessão do Windows.

**Correção.** Suíte de pull request só nos runners do GitHub. O PC do dono só
em push da `main` ou em disparo manual.

### B1 — Baixa — Metadado ausente no pagamento conta como certo

**Onde.** `backend/cobranca_mercadopago.py`, `_metadata_confere`: se o
pagamento não trouxer `chave_loja` no metadado, a função aceita. Valor,
moeda e `external_reference` continuam obrigatórios.

**Correção.** Quando a cobrança grava metadado, exigir que ele bata com a loja.
Não tratar “campo faltando” como sucesso.

### B2 — Baixa — Um segredo só administra a API e a central web

**Onde.** `PDV_API_TOKEN` é o bearer de administrador e a senha da central
(`/v1/fornecedor/login`). O Render pode gerá-lo (`render.yaml`,
`generateValue`). A comparação é em tempo constante. No Python 3.12.7 do
`render.yaml`, tamanho diferente não derruba o processo.

**Correção.** Senha da central diferente do token que os scripts usam.
Trocar se alguém que teve acesso ao ambiente sair.

### B3 — Baixa — CORS liberado no porteiro da nuvem

**Onde.** `backend/porteiro.py`, `_CORS` com `Access-Control-Allow-Origin: *`.
O cookie é `HttpOnly` e `SameSite=Lax`, e a resposta não pede
`Allow-Credentials`. Outro site não recebe o cookie do porteiro. O PIN tem
trava de tentativas.

**Correção.** Origem explícita no lugar de `*`.

### B4 — Baixa — Checkout do site sem limite de chamadas

**Onde.** `backend/site_checkout.py`, `criar_checkout`. Cada chamada grava
nome, e-mail, WhatsApp e nome da loja e abre uma preferência no Mercado Pago.
Não há 429. O preço ignorado no corpo está certo: o valor sai de
`site_precos`.

**Correção.** Limite por IP, no mesmo cuidado do item A4.

### B5 — Baixa — O Pix do caixa manda o valor com número decimal binário

**Onde.** `src/pagamentos/mercadopago_pix.py`, `round(valor_cent / 100, 2)`.
A cobrança da licença na nuvem usa `Decimal`.

**Correção.** Mandar o valor com `Decimal`, como em
`backend/cobranca_mercadopago.py`.

### B6 — Baixa — O filtro de segredo no erro do caixa é por palavra

**Onde.** `src/core/erros_caixa.py`. Tira bearer, e-mail, CPF, telefone e
linhas que tenham “token” ou “senha” antes do valor. Um segredo colado no
traceback sem essa palavra segue no lote para a nuvem.

**Correção.** Não enviar o traceback completo, ou cortar sequências longas
que pareçam segredo mesmo sem o nome ao lado.

## O que foi procurado e não virou achado

- **IDOR entre lojas.** As consultas do painel usam a chave da sessão. Gestão
  e importação recusam outra loja. Backup do caixa só devolve a loja do token.
  A central vê todas: é o papel do fornecedor, e o problema dela está no C1
  (o conteúdo do arquivo), não em “adivinhar o id”.
- **Open redirect** no 301 do site. Lista fechada de caminhos.
- **CSRF no painel.** O bearer não é cookie. O risco é roubo do token (A1, M4),
  não um POST cruzado.
- **Assinatura do webhook hoje desligada.** Os dois endpoints recusaram aviso
  sem `x-signature` (401). O M1 é o código que mudaria isso se a variável
  fosse apagada.
- **Segredo commitado.** Ver a seção do git, acima.
- **`npm audit`.** Não há aplicação Node com `package.json`. Os `.js` do
  painel, do site e da central são arquivos servidos pela API.
- **Stack trace na API.** `POST /v1/painel/login` com corpo inválido respondeu
  422 com a mensagem de validação, sem traceback.
- **Dependências da nuvem.** `pip-audit` em `backend/requirements.txt` e em
  `requirements-test.txt`: nenhum aviso. Os avisos do programa do caixa estão
  em A3 (Pillow) e M9 (`cryptography`).

## Corrigir primeiro

1. **C1.** Tirar o Access Token do Pix e a senha do certificado do backup que
   fica no Postgres, ou cifrar esse arquivo fora do banco.
2. **A1.** Desligar `/docs`, `/redoc` e `/openapi.json` em produção.
3. **A2.** Recusar `api_url` que não seja HTTPS (localhost continua valendo
   para teste).
4. **A3.** Pillow 13.0.0 no programa do caixa.
5. **A4.** Trava da central: só erro de senha, IP real do proxy do Render.
6. **M1.** Webhook do site recusar quando `MP_WEBHOOK_SECRET` estiver vazio.
7. **M2.** Senha temporária da rede obrigatória também em
   `/v1/painel/gestao/` e na importação.
8. **M8**, junto do C1. Parar de espelhar CPF sem necessidade e definir prazo
   para pedido, checkout e ficha que sobe no backup.
9. **M4.** Cabeçalhos (CSP, HSTS, anti-frame) e sessão do painel em cookie
   `HttpOnly`.
10. **M10, M9, M3, M5, M6, M7** e os itens baixos, nessa ordem, quando os de
    cima estiverem fechados. O `cryptography` (M9) sobe junto do Pillow.

Nenhuma dessas correções foi aplicada neste trabalho. Cada uma espera o
aceite do dono.
