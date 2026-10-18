# Gerar, baixar, instalar e testar o WillPDV no Windows

O GitHub Actions gera o programa para você: um instalador (`WillPDV-Setup-<versão>.exe`) e uma versão portátil (a pasta do
programa, sem instalar). Não precisa de Python nem de Inno Setup no seu PC.

## 1. Gerar o instalador

O workflow é o `.github/workflows/build-windows.yml` ("Gerar instalador (Windows)"). Ele roda sozinho a cada push na `main`
ou numa branch `claude/...`, e também sob demanda:

1. No GitHub, abra a aba **Actions** > **Gerar instalador (Windows)**.
2. **Run workflow**, escolha a branch e confirme. (O botão só aparece depois que o arquivo do workflow está na `main`; até lá,
   o push na branch já dispara a geração sozinho.)
3. Espere uns 6 a 12 minutos. Ao final a execução fica verde.

O workflow não entrega um programa quebrado: depois de gerar, ele **abre o programa empacotado** (autoteste: módulos, banco,
menu, telas e conexão HTTPS com o Telegram), **instala o instalador de verdade** num diretório de teste, roda o autoteste no
programa instalado e desinstala. Se qualquer etapa falhar, a execução fica vermelha e não há instalador para baixar.

## 2. Baixar

### O jeito mais fácil: aba Releases

A cada atualização da `main`, o instalador e a versão portátil são publicados na Release **"WillPDV - última versão"** (marcada
como *Pre-release*). Na página principal do repositório, olhe a coluna da direita, em **Releases**; ou use o link fixo:

* página: <https://github.com/GodFather-byte/PDV-CASA-/releases/tag/ultima-versao>
* instalador direto: <https://github.com/GodFather-byte/PDV-CASA-/releases/download/ultima-versao/WillPDV-Instalador.exe>
* versão portátil direta: <https://github.com/GodFather-byte/PDV-CASA-/releases/download/ultima-versao/WillPDV-Portatil.zip>

É o `.exe` direto, sem .zip em volta, e o nome não muda a cada versão. A Release é sobrescrita a cada atualização da `main`
(o título mostra a versão e o commit). O programa de licenças do fornecedor **não** vai para lá (a Release é pública).

### Pelos Artifacts (qualquer branch, inclusive o programa de licenças)

Abra a execução (clique no nome dela em Actions) e role até **Artifacts**:

| Artifact | O que é |
| --- | --- |
| `WillPDV-Instalador-<versão>-<commit>` | o instalador (`WillPDV-Setup-<versão>.exe`) dentro de um .zip que o GitHub cria |
| `WillPDV-Portatil-<versão>-<commit>` | a pasta do programa em .zip: extraia e rode `WillPDV.exe`, sem instalar |
| `autoteste-<commit>` | os relatórios do autoteste (útil se algo falhar) |
| `WillLicencas-Instalador-<versão>-<commit>` | o programa **do fornecedor** que emite as licenças (veja `docs/LICENCIADOR.md`); não é para o cliente |

Baixe o primeiro, extraia o .zip e use o `.exe` de dentro. A página da execução também mostra o tamanho e o SHA-256 do
instalador, para você conferir o arquivo. Os artifacts ficam 30 dias. Para um link fixo (que dá para mandar a um cliente), crie
uma tag: `git tag v1.2.0 && git push origin v1.2.0`. O instalador vai para a aba **Releases**, sem .zip.

## 3. Instalar

Dê dois cliques no `WillPDV-Setup-<versão>.exe` > Avançar > Instalar. O programa vai para `Arquivos de Programas\WillPDV`, com
atalho na Área de Trabalho e no Menu Iniciar.

- **"O Windows protegeu o seu computador" (SmartScreen):** o instalador ainda não tem assinatura digital paga, então o Windows
  desconfia de qualquer programa novo. Clique em **Mais informações > Executar assim mesmo**. Se o antivírus reclamar (é comum
  com programas empacotados em PyInstaller), libere o arquivo ou a pasta `WillPDV`.
- Windows de 64 bits.
- Os dados (banco, backups, licença, logs) ficam em `%LOCALAPPDATA%\WILL-PDV`, não na pasta do programa: atualizar ou
  desinstalar **não apaga as vendas**. Para atualizar, rode o instalador novo por cima (com o turno fechado).

## 4. Primeira abertura: banco e licença

### Interface Qt em migração

O atalho normal continua abrindo a interface Tk completa. O Menu Iniciar inclui
**WillPDV Qt (prévia)**, que abre a nova interface com `--qt`.
Não misture as duas interfaces ao mesmo tempo: elas usam o mesmo banco e a mesma
trava de instância. `--tk` seleciona explicitamente a interface anterior.

A prévia não significa que todas as telas foram migradas. Confira o escopo e
o roteiro de homologação em [INTERFACE_QT.md](INTERFACE_QT.md) antes de usá-la
numa noite de operação. Não há conversão para banco remoto: o caixa continua
SQLite local e a nuvem/licenças permanece separada.

Ao executar pelo código-fonte, instale `pip install -r requirements.txt`;
o instalador já leva Qt Widgets e as bibliotecas do backup seguro.
As bibliotecas Qt são maiores que Tk; o tamanho do pacote aumenta.
As licenças de terceiros ficam na pasta `licencas` do programa.

O comando `WillPDV.exe --autoteste-qt caminho-do-relatorio.txt` verifica a
interface Qt num banco temporário, sem usar as vendas da loja. O build executa
essa checagem tanto no programa empacotado quanto depois de instalá-lo.

### Proteção do banco durante atualização e restauração

- Antes de migrar um banco existente, o PDV gera e confere uma cópia SQLite ao lado dele
  (`.antes-migracao-v<versao>-<identificador>.bak`). Falha na cópia impede a migração.
- Uma versão antiga do PDV recusa banco de versão mais nova; não reinstale versões antigas para contornar erros.
- A restauração prepara e valida uma cópia antes de substituir o banco. Em falha, o pedido é preservado,
  o erro é mostrado e a abertura normal não pode criar um banco vazio no lugar do anterior.
- Continue mantendo backup em outro disco/local. Uma cópia no mesmo disco não protege contra perda do equipamento.

### Cópia criptografada em pasta sincronizada

Em **Utilitários > Backup externo criptografado**, escolha uma pasta já
sincronizada pelo OneDrive/Google Drive e uma senha de recuperação.
Não coloque o banco em uso dentro dessa pasta.
Guarde a senha fora do computador e teste a recuperação antes de depender dela.
O PDV confere o arquivo gerado, mas o envio à nuvem depende do sincronizador.
Veja configuração, recuperação em outra máquina e limitações em
[BACKUP_EXTERNO.md](BACKUP_EXTERNO.md).

### Consulta de licença sem travar a entrada

A tela consulta a rede em segundo plano e aplica o resultado na interface. Cliques repetidos não iniciam consultas
duplicadas. Fechar a janela não deixa uma resposta tardia aplicar alterações por trás.
Falhas de rede usam novas tentativas progressivas de 1 a 30 minutos; consultas concluídas mantêm o intervalo normal
de seis horas. O painel mostra a validade, a última consulta bem-sucedida e eventual falha da nuvem.
O vencimento, a carência e a proteção de turno recente permanecem iguais.

### Ativar uma licença manualmente

No programa instalado a licença é **sempre exigida**. Na tela de entrada, o botão **Código de licença...** pede um código que
**você** gera no seu PC (o que tem a chave privada), com Python instalado, na pasta do projeto:

```powershell
python -m tools.gerar_licenca emitir --loja TESTE --dias 30
```

Cole a linha que começa por `PDVL1.` e confirme. Depois entre com **ADM / ADM**: o sistema obriga a trocar a senha. Se você
ainda não tem o par de chaves, veja "WillPDV Licenças: o gerador de licenças" no `README.md` (ou `docs/LICENCIADOR.md`) (a chave pública que vai no programa é a de
`src/core/licenca.py`; um código só vale se foi emitido pela chave privada correspondente).

## 5. Roteiro rápido de teste (uns 15 minutos)

1. Entrar (ADM, trocar a senha) e olhar o **menu novo**: setas + Enter, letras de atalho, cartões do painel.
2. **Configurações > Loja**: cadastrar o nome da casa.
3. **Cadastros > Produtos**: criar 2 produtos; **Lançamentos > Estoque**: lançar saldo (`50 skol`).
4. **Caixa**: abrir turno com fundo de caixa, vender no balcão e numa comanda, pagar em dinheiro e Pix, cancelar um item e uma
   venda, fazer uma sangria, **fechar o turno** e olhar a diferença.
5. **Utilitários > Backup de dados** e conferir o aviso verde no menu.
6. **Telegram** (opcional): `docs/TELEGRAM.md`. Precisa de internet no PC.
7. Impressora térmica e gaveta, se tiver: Configurações > Máquinas (`docs/PILOTO.md`).

## 6. Se algo der errado

- **O instalador mostra "Os aplicativos a seguir estão usando arquivos que precisam ser atualizados: WillPDV":** é um
  `WillPDV.exe` que ficou rodando, às vezes escondido (sem janela). Deixe marcado *Fechar os aplicativos automaticamente* e clique
  em *Avançar*. A versão atual do instalador também avisa e encerra sozinho o que sobrou. Se ainda assim travar: `Ctrl + Shift +
  Esc` > aba **Detalhes** > clique com o direito em `WillPDV.exe` > **Finalizar tarefa** (faça nos que aparecerem) e rode o
  instalador de novo. As vendas não se perdem: o banco fica em `%LOCALAPPDATA%\WILL-PDV`, fora da pasta do programa.

- Rode o autoteste no PC (cria um relatório com o que está faltando):

  ```powershell
  & "C:\Program Files\WillPDV\WillPDV.exe" --autoteste "$env:USERPROFILE\Desktop\autoteste.txt" --rede
  ```

- Em **Utilitários > Pacote de suporte** o programa junta os registros de erro (nunca as vendas) para você me mandar.
- Os registros ficam em `%LOCALAPPDATA%\WILL-PDV\logs`.
- **Se o workflow ficar vermelho em poucos segundos**, sem rodar nenhum passo, o problema não é o código: o GitHub não está
  entregando uma máquina para o job (na API aparece `runner_id: 0`). Em geral é a conta: limite de uso ou cobrança do Actions
  (repositório privado gasta minutos, e o Windows gasta o dobro), ou o Actions desabilitado em *Settings > Actions > General*.
  Abra o job na aba Actions e leia a mensagem no topo; em *Settings > Billing and plans* veja o uso e o limite de gastos.

## Plano B: gerar no seu próprio PC com Windows (sem GitHub Actions)

1. Instale o **Python 3.12 de 64 bits** (python.org; deixe marcado "tcl/tk and IDLE" e "Add python.exe to PATH") e o
   **Inno Setup 6** (jrsoftware.org/isdl.php).
2. Baixe o projeto (botão *Code > Download ZIP* na branch, ou `git clone`) e abra o PowerShell na pasta.
3. Rode:

   ```powershell
   pip install -r requirements.txt pyinstaller
   python build_pdv.py
   .\dist\WillPDV\WillPDV.exe --autoteste "$env:USERPROFILE\Desktop\autoteste.txt" --rede
   ```

4. O instalador sai em `instalador\saida\WillPDV-Setup-<versão>.exe`; o autoteste deve terminar em "TUDO CERTO".

## Para quem mantém o sistema

- A cada versão nova: suba o número em `src/versao.py` e faça o push. O nome do artifact leva a versão e o commit.
- Módulo novo em `src/` precisa entrar em `MODULOS` (`src/autoteste.py`): um teste cobra isso, porque o PyInstaller só leva o
  que enxerga por `import` e o autoteste é quem prova que nada ficou de fora.
- Para gerar local, no Windows: `pip install -r requirements.txt pyinstaller` e `python build_pdv.py` (precisa do Inno Setup 6).
