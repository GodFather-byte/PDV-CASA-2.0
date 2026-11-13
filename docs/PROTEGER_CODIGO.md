# Proteger o código (repositório privado)

Objetivo: o código do WillPDV deixa de ser visível para qualquer pessoa, **sem** as lojas perderem as atualizações e
sem o CI ficar caro.

## Como fica

| O quê | Onde |
|------|------|
| Código | `GodFather-byte/PDV-CASA-2.0`, **privado** |
| Instaladores e pacotes de atualização | repositório **público só de downloads** (ex.: `GodFather-byte/willpdv-downloads`), sem código |
| Testes no Windows | no **PC com Windows do dono** (runner próprio, sem gastar minutos) |
| Testes no Linux, geração do instalador | no GitHub (contam na cota de 2.000 minutos por mês do plano Free) |

Por que não fechar e pronto: os caixas baixam o instalador e a atualização sem senha. Se os arquivos ficassem no
repositório privado, as lojas parariam de atualizar. O fluxo de publicação recusa publicar num repositório privado.

## Passo a passo (nesta ordem)

### 1. Repositório de downloads (5 minutos)

1. No GitHub: **New repository**, nome `willpdv-downloads`, **Public**, marque **Add a README**.
2. Crie um token só para ele: Settings (da sua conta) > Developer settings > Personal access tokens >
   **Fine-grained tokens** > Generate new token.
   - Repository access: **Only select repositories** > `willpdv-downloads`.
   - Permissions > Repository > **Contents: Read and write**. Nada mais.
   - Validade: 1 ano (anote na agenda para renovar).
3. No repositório do código (`PDV-CASA-2.0`) > Settings > Secrets and variables > Actions:
   - aba **Secrets** > New secret: nome `DOWNLOADS_TOKEN`, valor = o token. **Não mande o token por chat.**
   - aba **Variables** > New variable: nome `DOWNLOADS_REPO`, valor `GodFather-byte/willpdv-downloads`.

### 2. Publicar uma vez no repositório novo

Faça o merge de qualquer PR na `main` (ou rode "Gerar instalador (Windows)" e "Will Restaurante" à mão em Actions).
Confira em `willpdv-downloads` > Releases: `ultima-versao`, `ultima-versao-adega`, `ultima-versao-restaurante` e
as `atualizacao-...`.

### 3. Links de instalação da central (Render)

No Render, no serviço da nuvem > Environment, crie:

```
PDV_INSTALADOR_WILLPDV=https://github.com/GodFather-byte/willpdv-downloads/releases/download/ultima-versao/WillPDV-Instalador.exe
PDV_INSTALADOR_WILLADEGA=https://github.com/GodFather-byte/willpdv-downloads/releases/download/ultima-versao-adega/WillAdega-Instalador.exe
PDV_INSTALADOR_WILLRESTAURANTE=https://github.com/GodFather-byte/willpdv-downloads/releases/download/ultima-versao-restaurante/WillRestaurante-Instalador.exe
```

Abra cada link no navegador: tem que baixar.

### 4. Runner no PC com Windows

O PC precisa ficar ligado e com internet. De preferência crie um **usuário do Windows só para isso** (sem seus
arquivos pessoais).

1. Instale o **Git for Windows** (https://git-scm.com).
2. GitHub > `PDV-CASA-2.0` > Settings > Actions > Runners > **New self-hosted runner** > Windows. Siga os comandos que
   a página mostra (baixar, `config.cmd`). No final, responda **Y** para "run as service".
3. Em Settings > Secrets and variables > Actions > **Variables**: nome `RUNNER_WINDOWS`, valor
   `["self-hosted","Windows"]`.

O runner só é usado depois do passo 5. Com o repositório público ele é ignorado de propósito: qualquer pessoa poderia
abrir um PR e rodar código no seu PC.

### 5. Fechar o repositório

`PDV-CASA-2.0` > Settings > General > Danger zone > **Change visibility** > Private.

Depois confira:
- Actions > Testes: os trabalhos de Windows aparecem rodando no runner do seu PC.
- Settings (da conta) > Billing > Usage: o consumo de minutos do mês.

## Publicar versão (instaladores e atualização das lojas)

Desde este PR o merge na `main` **não** gera instalador nem atualização sozinho. Os testes continuam a cada PR. Quando
quiser soltar uma versão (pode juntar vários PRs), faça uma destas:

- peça ao Claude: "publica a versão";
- ou no GitHub: Actions > **Gerar instalador (Windows)** > Run workflow (branch `main`), e o mesmo em
  **Will Restaurante**.

Isso também é segurança: nenhum merge chega às lojas sem você decidir.

## Custo de minutos

Medido em 13/11/2026 (o GitHub arredonda cada trabalho para cima, minuto a minuto):

| Execução | Hoje (público) | Privado, com o Windows dos testes no seu PC |
|------|------|------|
| Testes (a cada PR e merge) | grátis | ~12 min (só Linux) |
| Gerar instalador WillPDV + Adega (a cada merge na main) | grátis | ~27 min (Windows conta em dobro) |
| Will Restaurante (a cada merge na main) | grátis | ~9 min |

Numa semana movimentada como a de 06 a 13/11 (48 execuções de testes, 21 de instalador, 17 do restaurante) isso daria
perto de **1.300 minutos**. Com o instalador só quando você manda (uma ou duas versões por semana), a mesma semana fica
perto de **650**, e o mês cabe nos 2.000. Se acabar, o GitHub **para** o CI até o mês virar (o limite de gasto vem em US$ 0); não chega cobrança.

Se o ritmo continuar alto, o próximo passo é gerar o instalador também na sua máquina, mas **só num PC dedicado ou numa
máquina virtual**: a geração instala o programa no Windows, cria a tarefa de atualização do SISTEMA, cria um usuário de
teste e mexe nos direitos do sistema. Um usuário separado do Windows não isola isso (vale para o PC inteiro). Outra
saída é juntar vários PRs antes de cada merge na main.

## O que isto não resolve

O instalador continua público e o programa é feito com PyInstaller: dá para extrair o código Python de dentro do .exe.
A licença (ed25519) impede gerar licença falsa, mas alguém pode remover a checagem no código extraído. O próximo passo
para isso é compilar com **Nuitka** (vira C compilado). Ver `.ai/HANDOFF.md`.
