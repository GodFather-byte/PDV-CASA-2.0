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
* A loja pode ter **mais de um caixa**: as vendas se somam e cada caixa aparece com o seu turno (seção "Mais de um caixa").
* A nuvem guarda só uma **janela recente** (120 dias de vendas): o histórico completo é o do PDV (seção "Limpeza automática").
* O cupom continua **NÃO FISCAL**; o painel não emite documento fiscal.

## O que o dono vê

| Aba | Conteúdo |
|---|---|
| **Hoje** | Faturamento, nº de vendas, ticket médio, cancelamentos (quantos e quanto), itens, descontos, vendas por hora, formas de pagamento, modalidade (balcão, mesa, entrega, caderneta), últimos 14 dias; seletor de dia |
| **Caixa** | Um cartão por caixa: turno aberto (nº, operador, abertura), valor inicial, recebido, esperado na gaveta, sangrias e suprimentos, vendas no turno, cancelamentos; abaixo, caderneta a receber e clientes devendo; entregas pendentes (somados dos caixas) |
| **Produtos** | Mais vendidos do dia com natural × gelada, economia dada no atacado; estoque controlado, zerados e a lista abaixo do mínimo (um bloco por caixa quando mais de um controla estoque) |
| **Vendas** | Cada venda do dia (mais recente primeiro) com itens (gelada marcada, cancelados riscados), pagamentos, canceladas em vermelho com o motivo; com mais de um caixa, de qual saiu |

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
  caderneta a receber, entregas pendentes e o relógio do caixa. Leva também a identificação do caixa (nº do terminal,
  descrição e nome do computador, de Configurações > Máquinas, e um código gerado na primeira vez).

Não sobe: dados de clientes além do nome na venda de caderneta/entrega, senhas, operadores além do nome, configurações,
produtos que não foram vendidos (fora os do estoque abaixo do mínimo), nada de garotas/comissões.

Vendas **abertas** (mesa, comanda, balcão em andamento) não aparecem no painel até fechar.

Ao ligar o painel, **todo o histórico ainda não enviado** do caixa sobe (em lotes de 200, de uma vez). A nuvem confirma tudo,
mas só guarda as vendas dentro da retenção (120 dias): as mais antigas não ocupam espaço nenhum.

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
   sobe (veja "O que sobe para a nuvem"; a nuvem guarda só os últimos 120 dias).
4. Passe ao dono: o endereço `https://nuvem.seusite.com.br/painel/`, a chave da loja (`ADEGA-CENTRO`) e a senha.

## O dono troca a própria senha (no PDV)

A senha que o fornecedor passou não precisa ficar para sempre. No caixa da loja (Tk ou Qt), com o endereço e o token da nuvem
já salvos em Configurações > Nuvem:

* **Tk:** Configurações > botão **Senha do painel do dono...** (na barra de cima, em qualquer aba). Grava antes o que está na
  tela e pede a senha duas vezes.
* **Qt:** Configurações > aba **Conexão com a nuvem** > **Trocar a senha do painel do dono…** (exige a aba salva: o endereço e o
  token usados são os salvos).

Mínimo de 8 caracteres. **Em branco**, a nuvem gera uma senha (`xxxx-xxxx-xxxx`) e ela aparece **uma única vez** na tela do
PDV: anote. A troca derruba as sessões abertas, então o celular do dono entra de novo com a senha nova. Usa o token da loja
(a rota `POST /v1/painel/senha`); a senha não fica gravada no PDV e o log registra só que foi trocada e por quem.

Se a nuvem não responder ou recusar o token, a tela diz que a senha **não** foi trocada e a antiga continua valendo. Quem
perdeu a senha troca por aqui mesmo (basta o caixa estar com a nuvem configurada) ou pelo fornecedor (`backend.lojas painel`).

## Mais de um caixa na loja

Cada caixa tem o seu próprio banco, então cada um **se identifica** na nuvem (um código gerado na primeira vez e guardado no
banco do caixa; se o banco for copiado para outro computador, o computador novo ganha o código dele) e a nuvem guarda **um
retrato por caixa**. Antes, o último a falar apagava o retrato do outro.

* **Vendas:** somam sozinhas (cada venda tem o seu uuid). Na aba Vendas aparece de qual caixa saiu cada uma.
* **Caixa:** um cartão por caixa, com "Aberto/Fechado", o computador e "atualizado às". Um caixa que não fala há mais de 10
  minutos ganha a etiqueta "Sem enviar há ...", sem alarmar o resto da tela.
* **Caderneta e entregas:** somadas dos caixas (cada caixa tem a sua caderneta; as somas ficam marcadas como tal).
* **Estoque:** **não se soma**: cada caixa tem o seu estoque, e dois caixas controlando estoque quase sempre divergem. Com um só
  caixa controlando, o bloco é o de sempre; com mais de um, um bloco "Estoque · nome do caixa" para cada. Para o estoque do
  painel ser um só, controle o estoque em um caixa só.
* **Nomes:** o cartão usa a **Descrição** da máquina (Configurações > Máquinas, ex.: "Bar", "Entrada"; vazio vira "Caixa N") e o
  nome do computador. Dê descrições diferentes a cada caixa.
* **Limites:** no máximo 20 caixas por loja (passando, sai o que está calado há mais tempo) e um caixa que não manda retrato
  há 14 dias sai da lista (volta sozinho quando falar de novo).
* **PDV de versão anterior** (que não se identifica) continua funcionando: entra como um caixa só. Quando ele atualiza, o
  retrato antigo some sozinho depois de 15 minutos sem ser renovado.

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
* 8 senhas erradas em 15 minutos bloqueiam a loja por 15 minutos (contagem por processo do servidor, que também esquece
  sozinha as tentativas vencidas: quem testa nomes de loja inventados não enche a memória).
* Cada loja só enxerga os próprios dados: todas as consultas filtram pela chave da loja da sessão.
* Desativar a loja (`backend.lojas desativar`) bloqueia o envio e o login do painel.
* O retrato e as vendas ficam no banco da nuvem (Neon/PostgreSQL ou SQLite local), com a limpeza automática abaixo. Para
  tirar **todos** os dados de uma loja, apague as linhas de `painel_vendas` e `painel_caixas` com a chave dela.
* O atraso mostrado usa o relógio da **nuvem** (quando o último envio chegou), não o do caixa.

## Limpeza automática

O PDV é o arquivo da loja; a nuvem guarda só o que o app consulta. A limpeza roda **sozinha**: na primeira vez que um PDV envia
depois de a nuvem subir e, depois, no máximo a cada 6 horas, em segundo plano (o envio não espera por ela). Apaga:

| O quê | Quando sai | Ajuste |
|---|---|---|
| Vendas do painel | passaram de **120 dias** (e nem entram se já chegam velhas) | variável `PDV_PAINEL_RETENCAO_DIAS` no servidor (mínimo 7; o histórico do app pede até 90) |
| Sessões do celular | venceram (30 dias de uso) | fixo |
| Retrato de um caixa | o caixa não manda há **14 dias** | fixo |

Nunca apaga lojas, senhas do painel nem o que está dentro dos prazos; repetir é seguro. Para rodar na hora e ver os números
(no PC, ligado ao banco da nuvem, como os outros comandos de `backend.lojas`):

```powershell
python -m backend.lojas limpar-painel
```

Uma tabela antiga (`painel_retratos`, um retrato por loja) é apagada sozinha na primeira subida da versão nova: o retrato é
só o último "momento" e cada caixa o refaz em cerca de 1 minuto.

## Publicar pelo GitHub Actions

O GitHub Actions **não hospeda** o painel: ele roda os testes e aciona o deploy. O workflow
`.github/workflows/nuvem-deploy.yml` faz isso a cada push em `main` que toque `backend/` ou `src/`:

1. instala as dependências da nuvem e roda os testes do painel (`tests.test_painel_dono`, `test_painel_caixas`,
   `test_painel_limpeza`, `test_painel_senha_pdv`) e `tests.test_nuvem`;
2. se passou e o segredo `RENDER_DEPLOY_HOOK_URL` existir, chama o Deploy Hook do Render (Render > serviço > Settings >
   Deploy Hook > copiar a URL > GitHub > Settings > Secrets and variables > Actions > New repository secret).

Sem o segredo o workflow só testa (útil para fork e pull request). Também dá para disparar à mão em Actions > "Nuvem:
testar e publicar" > Run workflow. GitHub Pages não serve para o painel: ele não executa a API e a política do Pages não
permite usá-lo como hospedagem de serviço comercial.

## Onde está no código

| Parte | Arquivo |
|---|---|
| Envio do caixa e identificação do caixa | `src/sync/painel_envio.py` (chamado por `src/sync/sincronizador.py`) |
| Troca da senha pelo PDV | `painel_envio.trocar_senha_na_nuvem` · telas `src/ui/config_ui.py` (`trocar_senha_painel`) e `src/ui_qt/configuracoes.py` |
| Configuração | `painel_dono` em `src/database/sementes.py` e `src/controllers/config_controller.py` (aba Nuvem) |
| Nuvem: tabelas, senha, sessão, rotas, limpeza | `backend/painel.py` (instalado por `backend/main.py`) |
| Senha e limpeza pela linha de comando | `python -m backend.lojas painel` e `python -m backend.lojas limpar-painel` |
| App web | `backend/painel_web/` (`index.html`, `app.js`, `estilo.css`, `sw.js`, `manifest.webmanifest`, `icones/`) |
| Ícones | `python -m tools.gerar_icones_painel` |
| Testes | `tests/test_painel_dono.py` (envio e nuvem), `test_painel_caixas.py` (vários caixas), `test_painel_limpeza.py`, `test_painel_senha_pdv.py` e `test_painel_senha_tk.py` (troca de senha), `test_qt_configuracoes.py` (a janela Qt) |

## Rotas da API

| Rota | Quem | O quê |
|---|---|---|
| `POST /v1/painel/envio` | token da loja | vendas (até 500 por chamada) e retrato; devolve os uuids guardados |
| `POST /v1/painel/senha` | token da loja | define (ou gera, se o corpo vier vazio) a senha do painel da própria loja: é o que o botão do PDV usa |
| `POST /v1/admin/lojas/{chave}/painel` | `PDV_API_TOKEN` | define (ou gera) a senha do painel da loja |
| `POST /v1/painel/login` | loja + senha | abre a sessão (30 dias) |
| `POST /v1/painel/sair` | sessão | encerra a sessão |
| `GET /v1/painel/resumo?dia=` | sessão | totais do dia, dias disponíveis e `caixas` (um item por caixa: turno, estoque, caderneta, entregas, atraso); `caixa`, `estoque`, `caderneta` e `entregas_pendentes` seguem no topo, calculados de todos os caixas, para o app antigo |
| `GET /v1/painel/vendas?dia=&pagina=` | sessão | vendas do dia, 50 por página (cada uma com o `terminal_id` do caixa) |
| `GET /v1/painel/historico?dias=14` | sessão | faturamento, vendas e canceladas por dia |
| `GET /painel/` | público | o app web (a API não expõe dados sem sessão) |
