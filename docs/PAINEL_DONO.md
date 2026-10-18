# Painel do dono no celular

O dono da loja acompanha **vendas, caixa, produtos e estoque** pelo celular, num aplicativo web que ele instala pelo
navegador ("Adicionar à tela inicial"), sem loja de aplicativos. Funciona para qualquer perfil (adega, comércio, bar,
boate); nasceu junto com o módulo Adega.

Como as peças se encaixam:

```text
Caixa da loja (WillPDV)  --- a cada rodada da sincronização --->  Nuvem (backend/)  <--- celular do dono (/painel/)
vende offline, guarda tudo                                     guarda a cópia por loja    lê, nunca altera
```

* O caixa **não depende** do painel para vender: sem internet as vendas esperam e sobem depois.
* O painel mostra o que **já subiu**: é um retrato recente, não uma tela ao vivo. Por isso ele destaca "Atualizado às
  HH:MM (há N min)" e avisa quando o caixa está sem falar com a nuvem.
* O painel é **só leitura**: nenhuma ação no celular mexe no caixa.
* O cupom continua **NÃO FISCAL**; o painel não emite documento fiscal.

## O que o dono vê

| Aba | Conteúdo |
|---|---|
| **Hoje** | Faturamento, nº de vendas, ticket médio, cancelamentos (quantos e quanto), itens, descontos, vendas por hora, formas de pagamento, modalidade (balcão, mesa, entrega, caderneta), últimos 14 dias; seletor de dia |
| **Caixa** | Turno aberto (nº, operador, abertura), valor inicial, recebido, esperado na gaveta, sangrias e suprimentos, vendas no turno, cancelamentos; caderneta a receber e clientes devendo; entregas pendentes |
| **Produtos** | Mais vendidos do dia com natural × gelada, economia dada no atacado; estoque controlado, zerados e a lista abaixo do mínimo |
| **Vendas** | Cada venda do dia (mais recente primeiro) com itens (gelada marcada, cancelados riscados), pagamentos, canceladas em vermelho com o motivo |

O "dia" é o **dia operacional** da loja (Configurações > Caixa > hora da virada): numa adega com virada às 6h, a venda
de 1h da manhã conta no dia anterior, igual aos relatórios do caixa. Cascos aparecem como produtos vendidos (não há saldo
de vasilhames por cliente, conforme a regra escolhida).

## O que sobe para a nuvem (e o que não sobe)

Só com **Configurações > Nuvem > "Painel do dono no celular" = Sim**. Desligado (padrão), nada sai da loja.

Sobe, a cada rodada da sincronização (`python -m src.app --sync`, normalmente a cada 60 s):

* as **vendas fechadas e canceladas** que ainda não subiram, com itens (nome, quantidade, preço, temperatura, observação)
  e pagamentos (forma e valor). A nuvem confirma o que recebeu e só então o caixa marca como enviada (`vendas.sincronizado`).
  Cancelar uma venda já enviada faz ela subir de novo com o status novo;
* um **retrato** do momento: turno aberto e seus totais, estoque controlado (contagens e até 50 produtos abaixo do mínimo),
  caderneta a receber, entregas pendentes e o relógio do caixa.

Não sobe: dados de clientes além do nome na venda de caderneta/entrega, senhas, operadores além do nome, configurações,
produtos que não foram vendidos (fora os do estoque abaixo do mínimo), nada de garotas/comissões.

Vendas **abertas** (mesa, comanda, balcão em andamento) não aparecem no painel até fechar.

## Ligar para uma loja (fornecedor)

1. A loja já precisa existir na nuvem e estar ligada no caixa (guia [NUVEM.md](NUVEM.md), seções 3 e 4).
2. Defina a **senha do painel** da loja. Ela é separada do token do caixa, de propósito: o dono digita a senha no celular e
   nunca vê o token.

   ```powershell
   python -m backend.lojas painel ADEGA-CENTRO            # gera uma senha fácil de ditar (xxxx-xxxx-xxxx) e mostra UMA vez
   python -m backend.lojas painel ADEGA-CENTRO MinhaSenhaForte   # ou a senha que você escolher (8+ caracteres)
   ```

   Sem terminal no servidor (Render grátis), faça pelo navegador ou `curl`, com o `PDV_API_TOKEN`:
   `POST https://nuvem.seusite.com.br/v1/admin/lojas/ADEGA-CENTRO/painel` com corpo `{}` (gera) ou `{"senha": "..."}`.
   Trocar a senha derruba as sessões abertas no celular.
3. No caixa da loja, **Configurações > Nuvem > Painel do dono no celular = Sim**. Na próxima rodada o histórico pendente
   sobe (vendas antigas que já estavam no banco não sobem: só o que fechar a partir daí e o que ainda estava marcado como
   não enviado).
4. Passe ao dono: o endereço `https://nuvem.seusite.com.br/painel/`, a chave da loja (`ADEGA-CENTRO`) e a senha.

## Instalar no celular (dono)

1. Abra o endereço do painel no navegador do celular (Chrome no Android, Safari no iPhone).
2. Entre com a loja e a senha. A sessão vale 30 dias; "Sair" encerra na hora.
3. **Android:** toque em "Instalar" no app (ou menu ⋮ > "Adicionar à tela inicial"). **iPhone:** botão Compartilhar >
   "Adicionar à Tela de Início". O ícone verde com a garrafa aparece como um aplicativo.
4. Sem internet o app abre e mostra os últimos números recebidos, com a faixa "Sem conexão: mostrando dados de HH:MM".
5. Depois de uma atualização da nuvem, o app novo entra na **segunda** abertura (a primeira usa a cópia guardada e baixa a
   nova em segundo plano). Os dados vêm sempre da API, nunca do cache.

O painel exige **HTTPS** (o Render já entrega; no servidor próprio, o Caddy da seção 2.5 do guia da nuvem). Em `http://`
puro, o navegador não instala o app e não guarda o cache offline.

## Segurança e limites

* Duas credenciais: o **token da loja** (só o caixa usa, envia dados) e a **senha do painel** (só lê). Nenhuma delas é
  guardada em texto puro na nuvem (SHA-256 do token; PBKDF2 da senha). O celular guarda só o token da sessão.
* 8 senhas erradas em 15 minutos bloqueiam a loja por 15 minutos (contagem por processo do servidor).
* Cada loja só enxerga os próprios dados: todas as consultas filtram pela chave da loja da sessão.
* Desativar a loja (`backend.lojas desativar`) bloqueia o envio e o login do painel.
* O retrato e as vendas ficam no banco da nuvem (Neon/PostgreSQL ou SQLite local). Não há apagamento automático; para
  limpar uma loja, apague as linhas de `painel_vendas` e `painel_retratos` com a chave dela.
* Um caixa só por loja: com dois terminais enviando, as vendas se somam (cada uma tem o seu uuid), mas o "retrato do
  caixa" é o do último que falou com a nuvem.
* O atraso mostrado usa o relógio da **nuvem** (quando o último envio chegou), não o do caixa.

## Publicar pelo GitHub Actions

O GitHub Actions **não hospeda** o painel: ele roda os testes e aciona o deploy. O workflow
`.github/workflows/nuvem-deploy.yml` faz isso a cada push em `main` que toque `backend/` ou `src/`:

1. instala as dependências da nuvem e roda `tests.test_painel_dono`, `tests.test_nuvem` e os testes de cobrança;
2. se passou e o segredo `RENDER_DEPLOY_HOOK_URL` existir, chama o Deploy Hook do Render (Render > serviço > Settings >
   Deploy Hook > copiar a URL > GitHub > Settings > Secrets and variables > Actions > New repository secret).

Sem o segredo o workflow só testa (útil para fork e pull request). Também dá para disparar à mão em Actions > "Nuvem:
testar e publicar" > Run workflow. GitHub Pages não serve para o painel: ele não executa a API e a política do Pages não
permite usá-lo como hospedagem de serviço comercial.

## Onde está no código

| Parte | Arquivo |
|---|---|
| Envio do caixa | `src/sync/painel_envio.py` (chamado por `src/sync/sincronizador.py`) |
| Configuração | `painel_dono` em `src/database/sementes.py` e `src/controllers/config_controller.py` (aba Nuvem) |
| Nuvem: tabelas, senha, sessão, rotas | `backend/painel.py` (instalado por `backend/main.py`) |
| Senha pela linha de comando | `python -m backend.lojas painel` |
| App web | `backend/painel_web/` (`index.html`, `app.js`, `estilo.css`, `sw.js`, `manifest.webmanifest`, `icones/`) |
| Ícones | `python -m tools.gerar_icones_painel` |
| Testes | `tests/test_painel_dono.py` |

## Rotas da API

| Rota | Quem | O quê |
|---|---|---|
| `POST /v1/painel/envio` | token da loja | vendas (até 500 por chamada) e retrato; devolve os uuids guardados |
| `POST /v1/painel/senha` | token da loja | define a senha do painel da própria loja |
| `POST /v1/admin/lojas/{chave}/painel` | `PDV_API_TOKEN` | define (ou gera) a senha do painel da loja |
| `POST /v1/painel/login` | loja + senha | abre a sessão (30 dias) |
| `POST /v1/painel/sair` | sessão | encerra a sessão |
| `GET /v1/painel/resumo?dia=` | sessão | totais do dia, caixa, estoque, caderneta, entregas, dias disponíveis |
| `GET /v1/painel/vendas?dia=&pagina=` | sessão | vendas do dia, 50 por página |
| `GET /v1/painel/historico?dias=14` | sessão | faturamento, vendas e canceladas por dia |
| `GET /painel/` | público | o app web (a API não expõe dados sem sessão) |
