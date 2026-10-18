# Backup externo criptografado

## O que este recurso faz

O PDV continua usando SQLite no computador, sem depender de internet para vender.
Além do backup local, pode gravar uma cópia **criptografada** numa pasta que o
OneDrive ou Google Drive já sincroniza. Não contrata armazenamento nem usa a API
dessas empresas. É o aplicativo de sincronização instalado que envia o arquivo.

**Arquivo criado não significa arquivo enviado.** O PDV verifica a recuperação
local do arquivo, mas não tem como afirmar que o provedor concluiu o upload.
Confira o ícone do sincronizador e a existência do arquivo no site do provedor.

Não coloque o banco em uso (`loja_offline.db`, `-wal`, `-shm`) numa pasta
sincronizada ou compartilhada. Sincronize somente os arquivos `.pdvbkp`.

## Configurar no Windows

1. Instale e entre no OneDrive/Google Drive com a conta escolhida pelo dono.
2. Crie uma subpasta exclusiva, por exemplo `OneDrive\WillPDV-Backups`.
3. No PDV, entre com um operador com acesso a **Utilitários > Backup**.
4. Abra **Utilitários > Backup externo criptografado > Configurar pasta e senha**.
5. Escolha essa subpasta. O programa sugere o OneDrive informado pelo Windows
   quando disponível, mas a escolha final deve ser conferida por você.
6. Crie e confirme uma senha de recuperação com pelo menos 12 caracteres.
   Prefira uma frase longa e exclusiva, não a senha do operador.
7. Guarde a senha em um gerenciador ou outro local seguro **fora do computador
   do caixa**. O fornecedor não pode recuperar ou redefinir a senha dos arquivos.
8. Escolha **Gerar cópia criptografada agora**.
9. Escolha **Testar recuperação de um arquivo** e informe a senha novamente.
10. Espere a sincronização e confira o arquivo pelo site do provedor.

O Windows protege uma cópia local da senha com **DPAPI do usuário atual**, num
arquivo terminado em `.backup.key` ao lado do banco. Ela permite backups
automáticos sem pedir a senha toda vez. Esse arquivo não é gravado no SQLite,
não vai dentro do backup e não deve ser publicado ou enviado ao suporte.

A proteção DPAPI não protege contra um programa malicioso executado como o
mesmo usuário do Windows. Proteja o acesso ao computador e à conta do provedor.

Se trocar de usuário, reinstalar o Windows ou mudar o computador, configure de
novo usando uma senha conhecida. **Os arquivos antigos continuam exigindo a
senha usada ao criá-los**; trocar a configuração não altera backups anteriores.

## Cópias automáticas e avisos

Quando um backup normal é feito, a pasta externa configurada recebe também uma
cópia criptografada. Os gatilhos de backup do sistema continuam os mesmos.
É possível gerar uma cópia externa manualmente sem esperar esses gatilhos.

- Arquivos: `loja_offline-seguro-<data>-<identificador>.pdvbkp`.
- Retenção padrão: 60 arquivos desse padrão; não remove arquivos de outros nomes.
- Antes de publicar cada arquivo, o PDV o descriptografa numa pasta temporária
  local e verifica se é um banco SQLite válido do PDV.
- A leitura/escrita da criptografia é feita em blocos, não carregando todo o
  banco na memória.
- Falha de pasta, disco ou cofre é registrada e aparece no estado do backup.
- Falha da cópia externa **não apaga o backup local nem impede a venda**.
- Um aviso de cópia externa verificada significa que o arquivo local foi
  recuperado com sucesso, **não que está disponível online**.

O backup local existente e a antiga opção de pasta extra continuam existindo e
podem conter SQLite **sem criptografia**. Não configure essas opções antigas
para uma pasta pública ou sincronizada quando precisar de confidencialidade.

## Recuperar no mesmo ou em outro computador

1. Instale uma versão do PDV compatível com o backup ou mais recente.
2. Baixe o `.pdvbkp` pelo provedor; confirme que o download terminou.
3. Abra o PDV e entre com um operador autorizado a restaurar backup.
4. Abra **Backup externo criptografado > Restaurar arquivo criptografado**.
5. Selecione o arquivo e informe a senha usada para gerá-lo.
6. Confirme a perda dos lançamentos feitos depois daquela cópia.
7. O PDV autentica e valida o arquivo, recusa bancos de versões futuras, guarda
   um backup do estado atual e marca a restauração para a próxima abertura.
8. Feche e abra o PDV. Confira produtos, vendas, turnos e relatórios antes de
   voltar a operar. Licença, equipamentos e credenciais restaurados também
   devem ser conferidos para o computador e a loja corretos.

Senha incorreta ou arquivo alterado/danificado não substituem o banco atual.
O teste de recuperação, sem restaurar, não modifica suas vendas.
A restauração usa o mecanismo local já existente de troca validada do banco.

Faça um exercício em **outro computador de teste**, com uma cópia dos dados,
antes de depender deste procedimento numa emergência.

## Formato e limitações

- Criptografia autenticada AES-256-GCM com sal e nonce aleatórios por arquivo.
- Derivação da senha com scrypt (`N=32768`, `r=8`, `p=1`).
- Cabeçalho versionado também autenticado. Arquivos truncados, adulterados ou
  com senha incorreta são recusados.
- Sem serviço de custódia ou recuperação de senha.
- Backups automáticos com senha persistida estão disponíveis no Windows.
  A leitura do formato criptografado é portátil; DPAPI não é.
- Nenhuma criptografia muda a licença comercial da loja ou garante recuperação
  se você perder simultaneamente arquivos e senha.
- Uma conta de sincronização pode propagar exclusões e ransomware. Mantenha
  também uma cópia desconectada ou retenção/versionamento do provedor.
- Perda da senha não se resolve reinstalando ou emitindo uma licença nova.

## Desativar

Use **Desativar cópias externas automáticas**. A configuração ativa e a senha
protegida local são removidas. Arquivos já gerados não são apagados; preserve
suas senhas de recuperação enquanto precisar deles.
