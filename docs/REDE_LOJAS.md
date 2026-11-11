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
