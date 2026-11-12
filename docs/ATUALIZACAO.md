# Atualização automática do caixa (Windows)

A partir da 1.14.4, o PDV aberto mantém verificador próprio, independente de sync_quase_tempo_real. Ele consulta a nuvem a cada 6 horas; o --sync também pode verificar. A abertura só retoma arquivo já baixado, sem esperar a rede.
Se houver pacote mais novo, **assinado** e com o SHA-256 certo, ele baixa em segundo plano e instala com o
Inno Setup em silêncio (`/VERYSILENT`) **só com turno fechado e sem venda, mesa ou comanda aberta**. Se o caixa
estiver ocupado, fica para a próxima abertura. Dá para adiar um dia, salvo atualização obrigatória ou
versão abaixo da mínima. Os dados continuam em `%LOCALAPPDATA%` (não vão na pasta do programa). Se a
versão nova não confirmar que subiu, o script copia a pasta anterior de volta e abre o programa de novo.
O PDV e o `--sync` são iniciados outra vez.

**Os caixas que ainda não têm esta versão precisam de um instalador manual, uma última vez.**

Edições: `willpdv`, `willadega`, `willrestaurante`, `bar` (a edição bar usa o mesmo mecanismo quando existir).

## Sem a janela de administrador (tarefa do Windows)

O programa fica em Arquivos de Programas e o instalador exige administrador; o PDV roda sem esse poder. Antes,
a instalação automática abria a janela "Deseja permitir que este app faça alterações?" e, sem ninguém para
clicar em Sim, falhava (a restauração também). Agora:

1. O instalador (que já roda como administrador) cria a tarefa agendada **`<Programa> Atualizacao`**
   (`WillPDV Atualizacao`, `WillAdega Atualizacao`, `WillRestaurante Atualizacao`), que roda como SISTEMA.
   Qualquer usuário pode iniciá-la, ninguém sem administrador pode alterá-la (`instalador/tarefa_atualizacao.ps1`).
   Também cria `%ProgramData%\<Programa>\atualizacao`, onde o PDV deixa o pedido.
2. O PDV baixa e confere o pacote, copia o instalador e o pacote assinado para essa pasta, inicia a tarefa e
   deixa rodando um script de espera (sem administrador) que reabre o programa quando sai o resultado.
3. A tarefa roda `<Programa>.exe --aplicar-atualizacao`, que **confere tudo de novo** (assinatura, edição, versão
   mais nova, tamanho e SHA-256), copia o instalador para uma pasta só do SISTEMA, guarda a cópia do programa e
   instala com o `aplicar.cmd` (confirma a versão nova sem tocar no banco; se falhar, restaura).
4. O resultado fica em `resultado-<id>.txt` na mesma pasta: `instalada`, `restaurada`, `falha_na_restauracao`
   ou `recusada: <motivo>`. Na abertura seguinte o PDV lê e registra.

Instalação antiga, sem a tarefa (ou tarefa recusada pelo Windows): cai no caminho de antes, que pede administrador.
**Por isso cada caixa precisa receber esta versão pelo instalador manual uma vez.** Código: `src/atualizacao/tarefa.py`.

## Quando instala sozinho

Sem o operador pedir, só com a loja parada: sem venda, mesa ou comanda aberta, sem turno aberto, sem impressão
na fila e com o último turno fechado há pelo menos 10 minutos (o fechamento ainda imprime). Se a instalação foi
disparada na abertura do programa, a tela não abre (o instalador a fecharia): aparece um aviso e o programa reabre
sozinho. Pelo botão **Instalar com o caixa livre**, basta não haver venda aberta.

A nuvem no Render pode levar perto de um minuto para acordar: a consulta espera até 60 s e, sem resposta, tenta de
novo em 15 minutos (antes esperava 6 horas). Pacote de outra edição é recusado antes do download.

## Tentativa que não subiu

Uma tentativa que não confirma (instalador falhou, restaurou, recusou o pacote ou nem começou) **para a
atualização automática daquele caixa**, para não fechar o programa em repetição. Agora isso aparece:

- no menu do PDV ("Atualização X não foi concluída") e em **Atualizações do programa**, com o motivo;
- na central do fornecedor, selo **Atualização travada** e o detalhe na ficha da loja (o caixa manda junto com o
  envio do painel, campo `atualizacao_travada`).

Para tentar de novo: no caixa, **Atualizações do programa > Instalar com o caixa livre**.

## Onde fica o arquivo

O repositório está público. O fluxo automático publica instaladores em Releases permanentes por edição e commit, antes de registrar o manifesto. Os links de “última versão” continuam para instalação manual; não servem de pacote assinado porque são substituídos. O Render não deve guardar o
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

Para caixas já instalados, recupere a semente correspondente à chave pública que eles reconhecem e guarde-a no segredo. Não gere outra só para preencher o segredo ausente. Uma chave diferente exige um plano de migração da confiança e pode exigir instalação manual.

## Publicar uma versão

1. Suba `VERSAO` em `src/versao.py` e faça merge na `main`. O Actions gera os instaladores.
2. O fluxo automático envia o `.exe` de cada edição ao Release permanente. No fluxo manual, hospede-o antes em um HTTPS público.
3. No GitHub, segredos do Actions (repositório, para ambos os workflows):
   - `PDV_ATUALIZACAO_CHAVE` — a semente
   - `PDV_NUVEM_URL` — a raiz da API, sem `/v1/...` (ex.: `https://seu-app.onrender.com`)
   - `PDV_API_TOKEN` — o token de administrador da nuvem
   - `PDV_ATUALIZACAO_BASE` não é mais exigido pelo fluxo automático; a hospedagem é o Release público permanente. O bucket existente pode continuar para pacotes manuais.
4. O workflow reutilizável `publicar-pacote.yml`, chamado pelos builds PDV/Adega/Restaurante, valida a chave, publica o instalador, confere o download público byte a byte, assina e chama `POST /v1/admin/atualizacao`.
   Sem segredos, com chave incompatível, erro de download ou hash diferente, a publicação falha explicitamente. Os instaladores manuais continuam disponíveis nos jobs separados.

Na mão, a mesma coisa:

```powershell
$env:PDV_ATUALIZACAO_CHAVE = "<64 hex>"
$env:PDV_NUVEM_URL = "https://seu-app.onrender.com"
$env:PDV_API_TOKEN = "<token>"
python -m tools.publicar_atualizacao WillPDV-Setup-1.10.1.exe --edicao willpdv --notas "Corrige o troco." --url https://atualizacoes.exemplo/willpdv/1.10.1/WillPDV-Setup-1.10.1.exe
python -m tools.publicar_atualizacao WillAdega-Setup-1.10.1.exe --edicao willadega --notas "Corrige o troco." --url https://atualizacoes.exemplo/willadega/1.10.1/WillAdega-Setup-1.10.1.exe
```

Obrigatória (não dá para adiar) e versão mínima:

```powershell
python -m tools.publicar_atualizacao WillPDV-Setup-1.10.1.exe --edicao willpdv --notas "Correção de dados." --url https://... --obrigatoria --minima 1.10.0
```

Republicar a mesma versão substitui o manifesto. O caixa confere a assinatura e o SHA-256 antes de instalar.

## No caixa

Menu **Atualizações do programa**: **Verificar atualizações**, **Adiar um dia**, **Instalar com o caixa livre**.
O aviso pequeno fica no menu principal. Atualização obrigatória não tem adiar.


## Diagnóstico de publicação parada

Em 12/11/2026 a API oferecia 1.12.0 para PDV/Adega, com assinatura e downloads válidos,
enquanto o build 1.14.0 passava sem publicar por falta de `PDV_ATUALIZACAO_CHAVE`.
O Restaurante era recusado na rota de manifestos. A correção não recupera a chave privada.
Reutilize a chave que gerou o pacote 1.12.0: trocar a chave pública do código impede os caixas
instalados de confiar nas novas versões. Não envie a chave em chat nem em arquivo do repositório.

O arquivo `manifesto.json` assinado fica nos artefatos e no Release do pacote; pode ser importado
em Atualizações na central. Pelo terminal, acrescente `--saida manifesto.json` ao comando de
publicação. A central não assina texto JSON digitado à mão. Um build ou deploy aprovado não
comprova que a loja instalou: confira a versão efetivamente informada por cada caixa.

Se o repositório voltar a ser privado, este fluxo falha antes de anunciar um download inacessível.
Será necessário configurar hospedagem HTTPS pública novamente. Não remover a verificação de assinatura.


## Contenção e recuperação de instalação

`PDV_ATUALIZACAO_PAUSADA=1` no Render impede a rota de oferecer novos pacotes.
Isso não desfaz pacotes já baixados nas máquinas. Em 12/11/2026 a Casa Verde
voltou a funcionar após executar manualmente o instalador 1.14.1; a causa local
não foi comprovada por logs. A oferta ficou pausada durante a correção.

A retomada corrigida consome o pendente antes de disparar e registra a tentativa;
uma tentativa não confirmada exige conferência em vez de repetir na abertura.
O script confere o código do instalador e um comprovante da versão nova, usa a
pasta original explicitamente e grava instalador.log/resultado.txt junto ao pacote.
A cópia anterior é preservada por versão. O instalador encerra processos do PDV
sem `/T`, para não matar os próprios processos filhos de instalação/recuperação.

O teste Windows executa o cmd real com instalador/executável controlados: sucesso,
falha de instalação, executável antigo retornando zero e encerramento do processo
pai. Não equivale a homologação de UAC/antivírus/reinício em cada loja. Só reativar
a oferta após validar a instalação completa no Windows. Máquinas com atualizador
antigo podem precisar receber a primeira correção pelo instalador manual.


## Correção inicial da consulta automática (1.14.4)

Nas versões até 1.14.3, o caminho padrão sem cliente HTTP injetado não consultava
os pacotes, e o serviço interno dependia da opção de envio quase em tempo real.
A correção resolve o HTTP padrão e mantém serviço dedicado à atualização no
aplicativo, mesmo com o envio de vendas desligado. Uma trava por banco evita
competição com --sync. A instalação automática aguarda o turno fechado; iniciar
manualmente continua possível com o caixa livre.

A primeira instalação da 1.14.4 nesses clientes deve ser feita pelo operador
com o instalador completo, ou por acesso remoto, sem exigir visita do fornecedor.
Não é possível corrigir pelo servidor um programa antigo que não faz a busca.
Depois disso, as próximas versões usam o mecanismo automático corrigido.

O CI abre cada executável instalado com banco e servidor HTTP fictícios, envio
quase em tempo real desligado, e exige consulta real automática sem fechar o PDV.
O teste não usa credenciais, licença ou banco de uma loja real.
