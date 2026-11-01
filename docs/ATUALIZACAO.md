# Atualização automática do caixa (Windows)

O caixa que já tem esta versão consulta a nuvem ao abrir e a cada 6 horas (`--sync` e o PDV aberto).
Se houver pacote mais novo, **assinado** e com o SHA-256 certo, ele baixa em segundo plano e instala com o
Inno Setup em silêncio (`/VERYSILENT`) **só quando não há venda, mesa ou comanda aberta**. Se o caixa
estiver ocupado, fica para a próxima abertura. Dá para adiar um dia, salvo atualização obrigatória ou
versão abaixo da mínima. Os dados continuam em `%LOCALAPPDATA%` (não vão na pasta do programa). Se a
versão nova não confirmar que subiu, o script copia a pasta anterior de volta e abre o programa de novo.
O PDV e o `--sync` são iniciados outra vez.

**Os caixas que ainda não têm esta versão precisam de um instalador manual, uma última vez.**

Edições: `willpdv`, `ea_superacoes`, `bar` (a edição bar usa o mesmo mecanismo quando existir).

## Onde fica o arquivo

O repositório é privado: o caixa não baixa o Release do GitHub. O Render também não deve guardar o
instalador (disco efêmero e o pedido estoura o tempo). O caminho barato é um **bucket HTTPS público**:

1. Conta gratuita no [Cloudflare R2](https://developers.cloudflare.com/r2/) (10 GB).
2. Bucket público, por exemplo `willpdv-atualizacoes`.
3. Cada versão: `willpdv/1.10.1/WillPDV-Setup-1.10.1.exe` e o equivalente da adega.
4. A URL pública entra no manifesto. O caixa baixa **direto** dessa URL. A nuvem só entrega o manifesto
   assinado (`GET /v1/atualizacao/ultima?edicao=willpdv&canal=estavel`).

Quem hospeda a API num servidor com disco pode, em vez do R2, colocar o `.exe` em
`PDV_ATUALIZACAO_DIR/<edicao>/<canal>/<versao>.exe`. A URL do manifesto fica
`/v1/atualizacao/arquivo?edicao=...&canal=estavel&versao=...`. A nuvem só envia o arquivo se o SHA-256
bater com o publicado.

## Chave (uma vez)

A chave **não** é a da licença. No seu computador, com o código desta versão:

```powershell
python -c "import secrets; from src.core.ed25519 import chave_publica; s=secrets.token_bytes(32); print(s.hex()); print(chave_publica(s).hex())"
```

- A primeira linha (64 hex) vai no segredo do GitHub `PDV_ATUALIZACAO_CHAVE` e em lugar nenhum do código.
- A segunda linha substitui `CHAVE_PUBLICA_HEX` em `src/atualizacao/manifesto.py`.

A chave pública que este repositório já traz corresponde à semente entregue junto com o PR. Guarde-a
no segredo antes de publicar. Se gerar outra, troque a pública e gere de novo o instalador que os
caixas vão receber na mão.

## Publicar uma versão

1. Suba `VERSAO` em `src/versao.py` e faça merge na `main`. O Actions gera os instaladores.
2. Envie o `.exe` de cada edição para o bucket (ou para `PDV_ATUALIZACAO_DIR`).
3. No GitHub, segredos do Actions (Environment ou repositório):
   - `PDV_ATUALIZACAO_CHAVE` — a semente
   - `PDV_NUVEM_URL` — a raiz da API, sem `/v1/...` (ex.: `https://seu-app.onrender.com`)
   - `PDV_API_TOKEN` — o token de administrador da nuvem
   - `PDV_ATUALIZACAO_BASE` — a URL pública do bucket, sem barra no fim
4. O job `Registrar manifesto da atualização` assina e chama `POST /v1/admin/atualizacao`.
   Sem os segredos ele só imprime o SHA-256 e não falha o build.

Na mão, a mesma coisa:

```powershell
$env:PDV_ATUALIZACAO_CHAVE = "<64 hex>"
$env:PDV_NUVEM_URL = "https://seu-app.onrender.com"
$env:PDV_API_TOKEN = "<token>"
python -m tools.publicar_atualizacao WillPDV-Setup-1.10.1.exe --edicao willpdv --notas "Corrige o troco." --url https://atualizacoes.exemplo/willpdv/1.10.1/WillPDV-Setup-1.10.1.exe
python -m tools.publicar_atualizacao EASuperacoes-Setup-1.10.1.exe --edicao ea_superacoes --notas "Corrige o troco." --url https://atualizacoes.exemplo/ea_superacoes/1.10.1/EASuperacoes-Setup-1.10.1.exe
```

Obrigatória (não dá para adiar) e versão mínima:

```powershell
python -m tools.publicar_atualizacao WillPDV-Setup-1.10.1.exe --edicao willpdv --notas "Correção de dados." --url https://... --obrigatoria --minima 1.10.0
```

Republicar a mesma versão substitui o manifesto. O caixa confere a assinatura e o SHA-256 antes de instalar.

## No caixa

Menu **Atualizações do programa**: **Verificar atualizações**, **Adiar um dia**, **Instalar com o caixa livre**.
O aviso pequeno fica no menu principal. Atualização obrigatória não tem adiar.
