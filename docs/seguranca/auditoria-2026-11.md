# Auditoria de segurança — novembro de 2026

Leitura do código do WillPDV (caixa, nuvem, painel, site, webhooks e retaguarda) e do histórico git.
Não houve teste de invasão, merge nem deploy. Na produção só foram feitas leituras: páginas e
`/health`, para ver cabeçalhos e se a documentação da API está aberta. Nenhum segredo é copiado aqui.

Produção observada em 24/11/2026: https://willpdv.com.br e https://willpdv-nuvem-6sp0.onrender.com
(as duas atrás da Cloudflare). `/docs`, `/redoc` e `/openapi.json` respondiam 200. As respostas não
traziam `X-Frame-Options`, `Content-Security-Policy`, `Strict-Transport-Security` nem
`X-Content-Type-Options`.

## Resumo

Não apareceu um furo em que o dono de uma loja leia a venda de outra (IDOR). O webhook da
mensalidade já exige a assinatura do Mercado Pago. O que estava aberto, e este trabalho fecha sem
mudar o protocolo do caixa 1.14.21:

- o aviso de pagamento do site podia ser aceito sem assinatura quando o segredo não estava definido;
- o painel podia ser colocado dentro de outra página (clique enganado que manda comando ao caixa);
- uma planilha Excel inchada podia derrubar o processo da nuvem;
- um hash de PIN com iterações absurdas podia travar o login do porteiro;
- a documentação viva da API (`/docs`) listava todas as rotas;
- a exportação CSV podia levar fórmula para o Excel.

Continua para o dono, fora deste código: senha da central separada do token da API, backup da loja
cifrado no banco da nuvem, e atualizar Pillow e cryptography quando a faixa de versões permitir.

## O que já está sólido

- Token da loja só é guardado como SHA-256. O token de administrador é comparado em tempo constante.
  Sem loja e sem `PDV_API_TOKEN`, a API recusa tudo.
- Senha do painel e da rede: PBKDF2-SHA256, 310 mil iterações, comparação em tempo constante.
  Senha do operador no caixa: PBKDF2, 600 mil iterações.
- Sessão do painel é um token opaco (não é JWT), guardado como hash, 30 dias, revogada quando a senha muda.
- Gestão, importação, NFC-e, notas, backup e retaguarda amarram a loja à sessão ou ao token.
  Pedir `loja=` de outra rede responde 403 ou 404 (`backend/gestao_painel.py`, função `loja_de`).
- Comando remoto tem lista fechada (cadastro, estoque, config, conta, planilha). Não há execução
  de programa nem SQL livre. O caixa só baixa a fila da própria loja, com o token dela.
  Configuração de nuvem, e-mail e integrações não é alterada por comando.
- Webhook da mensalidade (`/v1/webhooks/mercadopago`): HMAC do `x-signature`, prazo de 5 minutos,
  corpo ignorado, pagamento buscado na API do Mercado Pago, evento repetido não duplica.
- Atualização do caixa: manifesto Ed25519 e SHA-256 antes de instalar. A chave pública não é a da licença.
- Erros enviados pelo caixa passam por filtro de token, senha, e-mail e CPF (`src/core/erros_caixa.py`).
- Checkout do site ignora preço vindo do navegador. As URLs de volta são fixas (sem redirecionamento aberto).
- Central do fornecedor: cookie HttpOnly, SameSite estrito, CSRF nas alterações, limite de tentativas por IP.
- Não há `shell=True`. Identificadores SQL do caixa passam por uma lista de caracteres permitidos.

## Achados

### Alto — webhook do site aceitava aviso sem assinatura

Onde: `backend/site_checkout.py`, `processar_webhook` (antes desta correção).

O webhook da mensalidade para se `MP_WEBHOOK_SECRET` não existe. O do site
(`/v1/pagamentos/webhook`, também em GET) seguia em frente e usava o `data.id` da URL. O valor
aprovado ainda era conferido na API do Mercado Pago, então não dava para marcar um pedido como
pago sem um pagamento real. Dava para disparar consulta e processamento sem ser o Mercado Pago.

Correção feita: o site usa a mesma `validar_assinatura` da mensalidade. Sem segredo, responde 503.
Assinatura errada, 401. O caixa não chama essa rota.

### Alto — painel e retaguarda podiam ser enquadrados

Onde: respostas de `/painel/`, `/retaguarda/`, `/cardapio/` e `/porteiro/`. A central já mandava
`X-Frame-Options` e CSP; o resto não. Confirmado na produção (leitura dos cabeçalhos).

O painel guarda a sessão no `localStorage` e consegue enfileirar alteração de preço, estoque e
configuração para o caixa. Outro site pode abrir o painel num quadro invisível e induzir o dono a
clicar. Isso não é CSRF clássico (o navegador não manda o token sozinho), mas o quadro carrega a
página já logada.

Correção feita: toda resposta ganha `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`X-Content-Type-Options: nosniff` e `frame-ancestors 'none'`. Painel, retaguarda, cardápio e
porteiro também limitam script à própria origem. Em HTTPS (cabeçalho `X-Forwarded-Proto`, como no
Render) entra `Strict-Transport-Security` por 180 dias, sem incluir subdomínios. O caixa lê JSON e
ignora esses cabeçalhos.

### Alto — planilha Excel podia estourar a memória da nuvem

Onde: `src/controllers/importacao_produtos.py`, `_ler_xlsx`. A mesma leitura vale para o caixa e
para o painel. O ZIP da NFC-e já tinha limite; o XLSX não. Um arquivo pequeno pode anunciar
dezenas de megabytes por dentro ou trazer DTD. O processo é o mesmo que sincroniza os caixas: se
ele cai, a nuvem para para todo mundo.

Correção feita: no máximo 40 entradas e 8 MB descompactados, e rejeição de `<!DOCTYPE` / `<!ENTITY`.
Planilha normal de até 5.000 produtos continua passando.

### Alto — hash de PIN com iterações enormes

Onde: `backend/porteiro.py` (`guardar_retrato`) e `src/core/seguranca.py` (`conferir`). O caixa
envia o hash do PIN. O formato traz o número de iterações. Um número gigante faz o servidor
calcular PBKDF2 até travar. A senha do painel tinha o mesmo padrão em `backend/painel.py`
(`conferir_senha`), embora esse hash seja gerado na nuvem.

Correção feita: teto de 2.000.000 iterações. O caixa atual usa 600.000; hash antigo de 60.000
continua válido. Acima do teto o login falha na hora, em vez de pendurar o processo.

### Alto — um segredo abre a API e a central

Onde: `backend/main.py` (`autenticar`) e `backend/central_fornecedor.py` (login). `PDV_API_TOKEN`
é o Bearer de administrador e, até aqui, também a senha da página `/central/`. Quem vê um, entra
nos dois.

Correção feita, sem mudar o que já está no Render: se existir `PDV_CENTRAL_SENHA`, a central passa
a exigir só ela. Sem essa variável, o comportamento de hoje permanece (o caixa não usa essa senha).

### Alto — backup da loja na nuvem não é cifrado

Onde: `backend/backup_nuvem.py`, coluna `conteudo`. O arquivo é o SQLite do caixa, compactado,
com SHA-256 conferido e só a própria loja (ou a central) baixa. Quem lê o banco Postgres (Neon)
lê o movimento, os clientes e o token que estiver dentro do arquivo.

Não foi alterado. O caixa 1.14.21 baixa esse gzip e confere o SHA-256. Cifrar agora impediria a
restauração nas lojas que já estão em campo. O caminho futuro é um formato novo, com o antigo
ainda legível.

### Médio — documentação da API pública

Onde: `backend/main.py`, `FastAPI(...)` sem desligar `/docs`. Na produção as três URLs
(`/docs`, `/redoc`, `/openapi.json`) respondiam 200 nos dois domínios. Não entrega senha, mas
mostra o mapa das rotas.

Correção feita: `docs_url`, `redoc_url` e `openapi_url` ficam desligados.

### Médio — fórmula em CSV

Onde: `src/core/relatorio.py` (`para_csv`), `backend/gestao_painel.py` (exportação),
`backend/importacao_painel.py` (`csv_produtos`), `src/controllers/hotel_controller.py`
(`exportar_fichas`), `backend/central_web/app.js` (`exportarCsv`). Nome de produto ou hóspede
começando com `=`, `+`, `-` ou `@` vira fórmula quando alguém abre no Excel. As etiquetas do
caixa já tratavam isso. O XLSX gerado pelo sistema grava texto, não fórmula.

Correção feita: número no formato brasileiro (inclusive `-1.234,56`) continua número; o resto que
parece fórmula ganha apóstrofo. Não muda o arquivo que o caixa sincroniza.

### Médio — login do painel freia por loja, na memória

Onde: `backend/painel.py`, classe `_Tentativas`. Oito erros em 15 minutos por chave. Reinício do
Render zera a conta. Não há limite por IP (a central tem, por IP). A senha do painel tem no mínimo
8 caracteres e o hash é lento, então força bruta direta é cara, mas um ataque distribuído não é
parado pelo processo.

Recomendação: regra de taxa na Cloudflare em `POST /v1/painel/login` e `POST /v1/fornecedor/login`.
Não foi posta no código para não bloquear várias lojas atrás do mesmo acesso.

### Médio — sessão do painel no navegador por 30 dias

Onde: `backend/painel_web/app.js` (token no `localStorage`) e `backend/painel.py` (`DIAS_SESSAO`).
Os cabeçalhos novos reduzem quadro e script de outro site. Um script injetado na própria origem
ainda leria o token. Não há cookie HttpOnly no painel; trocar isso mudaria o aplicativo do celular
e não entrou nesta leva.

### Médio — Pillow 12.3.0 e cryptography 46.0.7

`pip-audit` nas versões travadas de `requirements.txt` e `backend/requirements.txt` (24/11/2026).
Não há `package.json`; não coube `npm audit`.

- `cryptography` 46.0.7: rodas com OpenSSL vulnerável (GHSA-537c-gmf6-5ccf, correção 48.0.1) e
  verificação de nome com curinga (PYSEC-2026-3554, correção 49 ou 50). O `requirements.in` prende
  `cryptography>=43,<47`.
- `Pillow` 12.3.0: várias falhas ao abrir imagem (memória e estouro no decodificador), correção na
  série 13. O `requirements.in` prende `Pillow>=12.3,<13`. O caixa usa Pillow no logotipo, não na
  API pública.

Não subi a versão aqui: a faixa foi escolhida de propósito e a troca mexe no instalador do caixa.
Não há CVE anunciado nos pacotes da API (FastAPI, Starlette, SQLAlchemy, psycopg) nessa lista.

### Médio — senha do operador no caixa é curta

Onde: `src/core/seguranca.py`. No máximo 10 letras ou números, sem diferenciar maiúsculas, por
exigência do manual. O hash mitiga cópia do banco; a senha em si é fraca para um gerente. Não foi
mudada para não contrariar o manual nem o caixa em campo.

### Baixo

- Porteiro na nuvem manda `Access-Control-Allow-Origin: *` (`backend/porteiro.py`). O cookie é
  HttpOnly; o risco é alguém usar um token Bearer que já vazou, a partir de outra origem.
- Cozinha local escuta em `0.0.0.0` sem TLS (`src/cozinha/servico.py`). É a rede da loja, com PIN.
- URL de pacote de atualização pode ser `http://`. O manifesto assinado ainda exige o SHA-256, então
  trocar o arquivo no caminho não instala outro programa. Vale exigir `https://` numa versão nova do caixa.
- `GET /v1/atualizacao/arquivo` é público de propósito (instalador publicado).
- Teste grátis (`POST /v1/site/teste`) devolve a senha do painel na resposta. Há limite por IP e por
  WhatsApp. Em HTTPS isso é o combinado do cadastro; não repetir a senha em log.
- Sal padrão do teste grátis é fraco se `PDV_SITE_SAL` não estiver definido (`backend/site_teste.py`).
- FastAPI não usa JWT. Não há injeção de SQL por concatenar texto do navegador. Não há endpoint de
  depuração além do que foi fechado (`/docs`).

## Segredos no git

`gitleaks` 8.28.0 no histórico inteiro (458 commits), com redação. Sete avisos, todos exemplo:

- documentação de cobrança com o texto de espaço reservado do token;
- testes com token e senha fictícios;
- um `curl` antigo em `docs/NUVEM.md` com trechos curtos de exemplo (a linha ainda é documentação, não credencial de produção).

Nada disso pede rotação. Não há `.env` nem chave privada no arquivo atual. As chaves Ed25519 no
código são públicas (licença e atualização), como o desenho exige.

## O que este PR altera (compatível com o caixa 1.14.21)

O caixa segue enviando `Authorization: Bearer` do token da loja, o mesmo JSON de sync, retaguarda,
backup, porteiro e painel. Não há comando novo nem campo obrigatório novo.

| Mudança | Efeito no caixa 1.14.21 |
|---|---|
| Webhook do site exige `x-signature` | Nenhum. O caixa não chama `/v1/pagamentos/webhook`. |
| Cabeçalhos HTTP | Nenhum. O cliente HTTP do caixa não os interpreta. |
| `/docs` desligado | Nenhum. |
| Teto de iterações do hash | Nenhum. O hash gerado hoje fica abaixo do teto. |
| Limite ao ler XLSX | Nenhum para planilha normal. |
| CSV com apóstrofo em fórmula | Nenhum na sincronização. Só no arquivo que uma pessoa abre no Excel. |
| `PDV_CENTRAL_SENHA` opcional | Nenhum enquanto a variável não existir no Render. |

## Ação manual do dono

1. **Mercado Pago e Render.** Confira se `MP_WEBHOOK_SECRET` está definido no serviço da nuvem e se
   é o mesmo segredo da aplicação no Mercado Pago (o da mensalidade já depende disso). Depois deste
   deploy, o pagamento do site deixa de se confirmar sozinho se o segredo estiver vazio ou diferente.
   Não troque a URL do webhook da mensalidade (`/v1/webhooks/mercadopago` no host onrender).
2. **Senha da central.** No Render, crie `PDV_CENTRAL_SENHA` com um valor diferente de
   `PDV_API_TOKEN`. Entre de novo em `/central/` com essa senha. Sessões antigas da central caem.
   O token da API continua só para os programas que já o usam. Enquanto a variável não existir,
   a central segue aceitando o token da API.
3. **Depois do deploy (este PR não publica).** Abra https://willpdv.com.br/docs e
   https://willpdv.com.br/openapi.json: devem responder 404. No painel, a resposta deve trazer
   `X-Frame-Options: DENY`. Se a Cloudflare não encaminhar `X-Forwarded-Proto: https`, o HSTS não
   sai da aplicação; nesse caso ligue o HSTS no painel da Cloudflare.
4. **Backup.** O banco da nuvem guarda o SQLite da loja sem cifra. Quem tiver acesso ao Postgres vê
   esses arquivos. Não mude o formato enquanto o caixa 1.14.21 precisar baixar o gzip atual.
5. **Dependências.** Pillow e cryptography têm avisos cuja correção está fora da faixa do
   `requirements.in`. Quando for subir, gere o lock de novo e rode o backup cifrado e a importação
   de logotipo no Windows.
6. **Opcional.** Limite de taxa na Cloudflare para o login do painel e da central. Defina
   `PDV_SITE_SAL` longo se o teste grátis estiver ligado e a variável ainda for o padrão do código.
