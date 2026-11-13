# Rede de lojas

Uma rede junta várias lojas de um mesmo dono. O dono entra uma vez no painel e vê o
total da rede. Cada loja continua com o próprio caixa, estoque, custo e relatórios.

O link do painel da rede é:

`/painel/?grupo=CHAVE`

`CHAVE` é a chave da rede (letras, números, ponto, `_` ou `-`). O número da rede
também abre: `/painel/?grupo=12`.

Exemplo, se a nuvem está em `https://exemplo.com` e a chave é `REDE-EXEMPLO`:

`https://exemplo.com/painel/?grupo=REDE-EXEMPLO`

A senha criada pelo administrador é temporária. No primeiro acesso o dono é obrigado
a trocar.

## Como o dono usa

Depois de entrar com o login da rede, o dono vê a **central da rede**: faturamento, custo e lucro de todas
as lojas no período (Hoje, Semana, Mês ou datas escolhidas) e um cartão por loja, com o faturamento, a
parte dela na rede, quantas vendas, o lucro e se o caixa está enviando.

Tocar num cartão abre o painel daquela loja, sem pedir senha. Dentro da loja aparece no topo, em todas
as abas, a faixa **‹ Todas as lojas**: é por ela que se volta para a central da rede. A volta continua
funcionando depois de recarregar a página ou de fechar e abrir o app. **Sair** encerra a loja e a rede.

Na página, a sessão da rede fica guardada em `willpdv.rede.*` (fora do prefixo do painel, que é apagado
a cada troca de loja). A sessão da loja aberta pela rede é encerrada na volta.

## App da rede no celular (sem loja de aplicativos)

O painel da rede se instala como aplicativo (PWA), de graça, em iPhone e Android:

- **iPhone (Safari):** abrir o link da rede, tocar em Compartilhar e em **Adicionar à Tela de Início**.
- **Android (Chrome):** abrir o link da rede, menu ⋮ e **Instalar app** (ou o botão "Instalar agora" na tela da rede).

O ícone aparece com o **nome da rede** e abre direto no login dela. Isso vem do manifesto
`/painel/rede.webmanifest?grupo=CHAVE` (nome da rede, `start_url` `/painel/?grupo=CHAVE`); rede desconhecida recebe o
manifesto comum do painel. Na tela da rede há o quadro "Ter o app da rede no celular" com essas instruções.

## Mensalidade única pela central

Na central do fornecedor, aba **Redes**, cada rede tem **Mensalidade da rede**: valor, dia do vencimento e dados do
pagador (os mesmos do plano de uma loja). Ao salvar (com motivo, que fica na auditoria) a nuvem cria ou atualiza o plano
da rede e gera as cobranças devidas. Quando o pagamento é aprovado, a licença de todas as lojas da rede avança junto; as
cobranças próprias dessas lojas param enquanto elas estiverem na rede. Rota: `POST /v1/fornecedor/grupos/CHAVE/plano`
com `{"plano": {...}, "motivo": "..."}`.

## Criar pela API (token de administrador)

```http
POST /v1/admin/grupos
Authorization: Bearer <PDV_API_TOKEN>
Content-Type: application/json

{"nome": "Nome da rede", "chave": "REDE-EXEMPLO", "senha": "senha-temporaria", "temporaria": true}
```

A resposta traz `link` (`/painel/?grupo=REDE-EXEMPLO`) e `senha` só quando a senha
foi gerada pela nuvem. Se você enviou a senha, ela não volta na resposta.

Incluir e tirar loja:

```http
POST /v1/admin/grupos/REDE-EXEMPLO/lojas
{"chave_loja": "LOJA-1"}

DELETE /v1/admin/grupos/REDE-EXEMPLO/lojas/LOJA-1
```

Nova senha temporária:

```http
POST /v1/admin/grupos/REDE-EXEMPLO/senha
{"temporaria": true}
```

A mensalidade é uma só para a rede, no mesmo formato da loja, em
`POST /v1/admin/grupos/REDE-EXEMPLO/assinatura`. Quando o pagamento é aprovado, a
licença de todas as lojas da rede avança juntas. Enquanto a loja está na rede, a
cobrança individual dela não é gerada. Loja sem rede continua com a própria mensalidade.

A mesma gestão existe na central do fornecedor, na aba Redes
(`/v1/fornecedor/grupos`), depois de entrar com a credencial administrativa.
