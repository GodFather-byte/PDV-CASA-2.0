# Nuvem do WillPDV: como colocar no ar e acompanhar as lojas

A nuvem é a parte que fica com **você**, o fornecedor. Ela faz quatro coisas (cada loja continua guardando as próprias
vendas no caixa; só a que ligar o painel do dono manda uma cópia para a nuvem):

| O quê | Para quê |
|---|---|
| Guarda até quando cada loja pagou | O caixa renova a licença **sozinho** quando a loja está em dia |
| Avisa sobre versão nova | Aparece uma faixa no caixa: "Nova versão disponível" |
| Bloqueia uma loja | Desativou: a loja deixa de renovar a licença e de ver avisos |
| Painel do dono no celular (opcional) | O dono da loja acompanha vendas, caixa e estoque em `/painel/`; guia em [PAINEL_DONO.md](PAINEL_DONO.md) |

O caixa **não depende** da nuvem para vender: sem internet ele continua funcionando e tenta renovar a licença depois.

Tudo o que é da nuvem está na pasta `backend/` do projeto.

**Cobrança automática da mensalidade:** veja o guia separado
[Cobrança de licenças com Asaas](COBRANCA_LICENCAS_ASAAS.md). Ele explica vínculo
por loja, webhook, conciliação, custos e homologação. Para cobranças reais,
não use o Render gratuito descrito abaixo: escolha serviço sempre ligado e banco persistente.

---

## 1. Testar no seu computador (10 minutos)

Antes de alugar servidor, veja funcionando no seu PC (Windows):

```powershell
cd C:\caminho\do\PDV-CASA-
pip install -r backend\requirements.txt
$env:PDV_API_TOKEN = "minha-senha-de-administrador-bem-longa"
python -m backend.lojas criar BOATE-TESTE "Boate Teste"
python -m uvicorn backend.main:app --port 8000
```

- O `criar` mostra o **token da loja**. Copie: ele só aparece uma vez.
- Abra `http://localhost:8000/v1/saude` no navegador: deve mostrar `{"status":"ok"}`.
- Para ligar um caixa nesse teste, siga o passo 4 usando o endereço `http://localhost:8000`.

Para parar o servidor, aperte `Ctrl+C`.

---

## Opção grátis para começar: Render + Neon

Dá para colocar a nuvem no ar **sem pagar nada**, usando dois serviços gratuitos:

- **Render** ([render.com](https://render.com)): roda o programa da nuvem.
- **Neon** ([neon.tech](https://neon.tech)): guarda os dados (lojas e licenças) num banco PostgreSQL.

O banco precisa ficar fora do Render porque o disco do plano grátis do Render é apagado a cada reinício: as lojas e os
tokens sumiriam. No Neon os dados ficam guardados.

**Limitações do plano grátis (para saber antes):**

| O quê | Na prática |
|---|---|
| O Render "dorme" depois de 15 minutos sem uso | O primeiro acesso depois disso demora cerca de 1 minuto. O caixa não trava: o envio tenta de novo sozinho, e a licença manual continua valendo. |
| Neon grátis: 0,5 GB | Sobra de muito: guarda só a lista de lojas e as datas pagas. |
| Sem terminal no Render grátis | Os comandos de lojas e licenças (passos 3 e 5) rodam **no seu PC**, ligados ao banco do Neon (veja abaixo). |

Quando tiver várias boates pagando, passe para o VPS da seção 2 ou para um plano pago do Render. É só mudar o endereço
no caixa.

### G1. Criar o banco no Neon
1. Crie a conta em [neon.tech](https://neon.tech) (dá para entrar com o GitHub) e crie um projeto (região: São Paulo,
   se aparecer, ou a mais próxima).
2. Em **Connection string**, copie o endereço. Ele começa com `postgresql://` e termina com `?sslmode=require`.
   Guarde-o: é a "chave" do seu banco.

### G2. Subir a nuvem no Render
1. Crie a conta em [render.com](https://render.com) entrando com o **GitHub** e autorize o acesso ao repositório
   `PDV-CASA-`.
2. Clique em **New > Blueprint** e escolha o repositório. O Render lê o arquivo `render.yaml` do projeto e já
   preenche tudo.
3. Ele pede o valor de **PDV_NUVEM_DB_URL**: cole o endereço do Neon (passo G1).
4. Para a renovação automática da licença: no serviço criado, abra **Environment > Secret Files > Add Secret File**.
   - Nome do arquivo: `licenca_privada.key`
   - Conteúdo: o conteúdo do seu `C:\Users\SEU_USUARIO\.pdv-casa\licenca_privada.key`, que é uma linha de letras e números.
5. Clique em **Deploy**. Quando terminar, o Render mostra o endereço, algo como `https://willpdv-nuvem.onrender.com`.
   Abra `https://willpdv-nuvem.onrender.com/v1/saude`: tem que aparecer `{"status":"ok"}`.
6. A sua senha de administrador (para listar todas as lojas) está em **Environment > PDV_API_TOKEN**.

### G3. Rodar os comandos de lojas e licenças no seu PC
Como o banco está no Neon, os comandos funcionam do seu computador. No PowerShell, dentro da pasta do projeto:

```powershell
pip install -r backend\requirements.txt
$env:PDV_NUVEM_DB_URL = "postgresql://...cole-aqui-o-endereco-do-neon..."
python -m backend.lojas criar BOATE-ESTRELA "Boate Estrela"
python -m backend.lojas listar
python -m backend.lojas assinatura BOATE-ESTRELA 2026-11-30
```

A linha do `$env:` precisa ser repetida cada vez que abrir um PowerShell novo. Daí em diante, os passos **3 a 6**
deste guia funcionam igual: só troque `lojas` por `python -m backend.lojas` e `atualizacoes` por
`python -m backend.atualizacoes`.

No caixa (passo 4), o endereço fica: `https://willpdv-nuvem.onrender.com`.

Para atualizar a nuvem quando o código mudar, não precisa fazer nada: o Render publica sozinho a cada mudança no `main`
do GitHub.

---

## 2. Colocar no ar de verdade (servidor na internet)

O caminho mais simples e barato é um **VPS com Ubuntu**: Hostinger, DigitalOcean, Contabo, Magalu Cloud etc.
O plano mais barato (1 GB de RAM) dá conta de muitas lojas. Você também precisa de um **domínio**, por exemplo
`nuvem.seusite.com.br`, apontado para o IP do servidor (um registro tipo **A** no painel onde comprou o domínio).

Entre no servidor pelo terminal (`ssh root@IP-DO-SERVIDOR`) e rode os blocos abaixo, um de cada vez.

### 2.1 Programas e código

```bash
apt update && apt install -y python3 python3-venv git
mkdir -p /opt/willpdv && cd /opt/willpdv
git clone https://github.com/GodFather-byte/PDV-CASA-.git app
python3 -m venv /opt/willpdv/venv
/opt/willpdv/venv/bin/pip install -r app/backend/requirements.txt
```

> O repositório é privado, então o `git clone` vai pedir usuário e senha do GitHub. No lugar da senha use um
> **token de acesso pessoal** (GitHub > Settings > Developer settings > Personal access tokens).

### 2.2 A chave da licença (para a renovação automática)

Copie o seu arquivo `licenca_privada.key`, que fica no seu PC em `C:\Users\SEU_USUARIO\.pdv-casa\`, para o servidor.
Rode isto **no seu PC**:

```powershell
scp C:\Users\SEU_USUARIO\.pdv-casa\licenca_privada.key root@IP-DO-SERVIDOR:/opt/willpdv/
```

Depois, **no servidor**:

```bash
chmod 600 /opt/willpdv/licenca_privada.key
```

Sem esse arquivo a nuvem funciona, mas não emite licença: aí você manda o código manual como antes.

### 2.3 Configuração (senhas e caminhos)

```bash
cat > /opt/willpdv/nuvem.env <<'EOF'
PDV_API_TOKEN=TROQUE-POR-UMA-SENHA-LONGA-SO-SUA
PDV_NUVEM_DB_URL=sqlite:////opt/willpdv/nuvem.db
PDV_LICENCA_CHAVE=/opt/willpdv/licenca_privada.key
EOF
chmod 600 /opt/willpdv/nuvem.env
```

- `PDV_API_TOKEN` é a **sua** senha de administrador. Com ela você lista todas as lojas.
- Opcional: `PDV_PAINEL_RETENCAO_DIAS=120` (padrão) é quantos dias de vendas o painel do dono guarda na nuvem; o que passa disso
  é apagado sozinho (o histórico completo continua no PDV). Mínimo 7. Detalhes em [PAINEL_DONO.md](PAINEL_DONO.md), "Limpeza
  automática".

### 2.4 Deixar a nuvem ligada sempre (reinicia sozinha se cair ou se o servidor reiniciar)

```bash
cat > /etc/systemd/system/willpdv.service <<'EOF'
[Unit]
Description=WillPDV - nuvem
After=network.target

[Service]
WorkingDirectory=/opt/willpdv/app
EnvironmentFile=/opt/willpdv/nuvem.env
ExecStart=/opt/willpdv/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now willpdv
systemctl status willpdv --no-pager
```

### 2.5 HTTPS (cadeado) com o Caddy

O Caddy coloca o cadeado de graça e renova sozinho. Sem HTTPS, o token da loja trafega aberto na internet.

```bash
apt install -y caddy
cat > /etc/caddy/Caddyfile <<'EOF'
nuvem.seusite.com.br {
    reverse_proxy 127.0.0.1:8000
}
EOF
systemctl reload caddy
```

Troque `nuvem.seusite.com.br` pelo seu domínio. Para testar, abra `https://nuvem.seusite.com.br/v1/saude`: tem
que aparecer `{"status":"ok"}`.

### 2.6 Backup diário da nuvem

```bash
mkdir -p /opt/willpdv/backup
cat > /etc/cron.daily/willpdv-backup <<'EOF'
#!/bin/sh
/opt/willpdv/venv/bin/python -c "import sqlite3,datetime; o=sqlite3.connect('/opt/willpdv/nuvem.db'); d=sqlite3.connect('/opt/willpdv/backup/nuvem-'+datetime.date.today().isoformat()+'.db'); o.backup(d)"
find /opt/willpdv/backup -name 'nuvem-*.db' -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/willpdv-backup
```

Isso guarda uma cópia por dia e apaga as que têm mais de 30 dias. De vez em quando baixe uma cópia para o seu PC.

---

## 3. Cadastrar uma boate nova

Sempre **no servidor**, dentro da pasta do programa:

```bash
cd /opt/willpdv/app
set -a; . /opt/willpdv/nuvem.env; set +a
/opt/willpdv/venv/bin/python -m backend.lojas criar BOATE-ESTRELA "Boate Estrela"
```

Guarde o **token** que aparecer: ele vai no caixa da boate e não aparece de novo.

Use **o mesmo nome de loja** (`BOATE-ESTRELA`) na licença manual (`tools.gerar_licenca emitir --loja BOATE-ESTRELA`).

> Dica: para não repetir as duas primeiras linhas toda vez, crie um atalho:
> `echo 'alias lojas="cd /opt/willpdv/app && set -a && . /opt/willpdv/nuvem.env && set +a && /opt/willpdv/venv/bin/python -m backend.lojas"' >> ~/.bashrc`
> e abra o terminal de novo. Daí em diante basta `lojas listar`, `lojas criar ...` e assim por diante.

---

## 4. Ligar o caixa da boate na nuvem

No caixa, entre em **Configurações > Configurações > aba Nuvem**:

| Campo | O que colocar |
|---|---|
| Chave da loja (licença) | `BOATE-ESTRELA` |
| Endereço da nuvem | `https://nuvem.seusite.com.br` |
| Token da API | o token que o `criar` mostrou |
| Painel do dono no celular | **Sim** só se o dono quiser acompanhar pelo celular (as vendas passam a subir para a nuvem; veja [PAINEL_DONO.md](PAINEL_DONO.md)) |

Na instalação, marque **"Verificar licença e atualizações na nuvem em segundo plano"**: a verificação passa a abrir
sozinha junto com o Windows. Se o caixa já estiver instalado, rode o instalador de novo e marque essa opção. O histórico
fica em `%LOCALAPPDATA%\WILL-PDV\logs\sync.log`.

---

## 5. Acompanhar e controlar as licenças

**Pelo navegador ou `curl`:** a lista das lojas (ativa ou não, até quando pagou, "vence em" e "VENCIDA") sai em
`https://nuvem.seusite.com.br/v1/admin/lojas`, com o cabeçalho `Authorization: Bearer <seu PDV_API_TOKEN>`:

```bash
curl -H "Authorization: Bearer SEU_TOKEN_DE_ADMIN" https://nuvem.seusite.com.br/v1/admin/lojas
```

**Pelo terminal** (para cadastrar, renovar e bloquear):

Todos estes comandos são rodados no servidor (veja a dica do atalho `lojas` no passo 3):

```bash
lojas listar                                   # todas as lojas: ativa ou não, e até quando pagou
lojas assinatura BOATE-ESTRELA 2026-11-30      # a loja pagou até 30/11/2026
lojas assinatura BOATE-ESTRELA cancelar        # parou de pagar: não renova mais
lojas desativar BOATE-ESTRELA                  # bloqueia a loja na hora
lojas ativar BOATE-ESTRELA                     # libera de novo
lojas novo-token BOATE-ESTRELA                 # token vazou: gera outro (o antigo para de funcionar)
```

O `listar` mostra algo assim:

```
BOATE-ESTRELA            ativa    paga até 30/11/2026                    Boate Estrela
BOATE-SOL                ativa    paga até 06/10/2026 (vence em 2 dias)  Boate Sol
BOATE-LUA                INATIVA  paga até 01/09/2026 (VENCIDA)          Boate Lua
```

Fique de olho nas marcadas com **vence em** (cobrar) e **VENCIDA**.

**Como a renovação funciona no dia a dia:**

1. A boate paga o mês.
2. Você roda `lojas assinatura BOATE-ESTRELA <nova data>`.
3. Em até 6 horas o caixa busca o código novo sozinho. Ao entrar no sistema com a licença vencida, ele também tenta
   na hora.
4. Se a boate não pagar, a data não muda. O caixa avisa 7 dias antes, dá 5 dias de carência e nunca trava com o
   turno aberto.

Uma boate sem internet continua usando o código manual: `python -m tools.gerar_licenca emitir --loja ... --dias 30`.

---

## 6. Avisar as boates sobre uma versão nova

Depois de gerar o instalador novo e deixá-lo num link para baixar (Google Drive, Dropbox, seu site):

```bash
cd /opt/willpdv/app && set -a && . /opt/willpdv/nuvem.env && set +a
/opt/willpdv/venv/bin/python -m backend.atualizacoes publicar 1.2.0 --notas "Impressões novas e comissão por pontos." --url https://link-do-instalador
/opt/willpdv/venv/bin/python -m backend.atualizacoes listar
```

Com `--critica`, a faixa no caixa fica vermelha. Use para correções de dinheiro ou de dados.

---

## 7. Atualizar a nuvem quando o código mudar

```bash
cd /opt/willpdv/app && git pull
/opt/willpdv/venv/bin/pip install -r backend/requirements.txt
systemctl restart willpdv
```

Colunas novas no banco da nuvem são criadas sozinhas, sem perder o que já está lá.

**Pelo GitHub Actions:** o workflow `.github/workflows/nuvem-deploy.yml` roda os testes da nuvem a cada push em `main` que
mexa em `backend/` ou `src/` e, se passarem, aciona o deploy no Render pelo *Deploy Hook* guardado no segredo
`RENDER_DEPLOY_HOOK_URL` do repositório (Render > serviço > Settings > Deploy Hook). Sem o segredo, o workflow só testa. O
Actions **não hospeda** a nuvem: ele testa e publica; quem fica no ar é o Render (ou o seu servidor da seção 2).

---

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `https://.../v1/saude` não abre | `systemctl status willpdv` e `systemctl status caddy`. Confira se o domínio aponta para o IP do servidor. |
| Caixa não renova a licença nem mostra versão nova | Endereço ou token errado no caixa, ou a verificação não está aberta (passo 4). Veja o `sync.log`. |
| "Este token é da loja X" | A chave da loja no caixa não é a mesma do `criar`. |
| Licença não renova sozinha | `lojas listar` mostra a data paga? A data precisa ser **depois de hoje**. Confira também se o `licenca_privada.key` está no servidor (passo 2.2). |
| Ver os erros da nuvem | `journalctl -u willpdv -n 100 --no-pager` |
