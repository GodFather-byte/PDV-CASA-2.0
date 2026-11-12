# Handoff — Atualização automática sem a janela de administrador (12/11/2026)

Branch `atualizacao-sem-uac`, criada da main depois do merge do #83 (consulta automática) e do #84 (menu).
Pedido do dono: "as atualizações automáticas estão erradas". Guia atualizado: `docs/ATUALIZACAO.md`.

## O que estava errado e o que mudou

1. **Pedia administrador.** O instalador tem `PrivilegesRequired=admin`; o PDV roda sem. A automática abria a janela
   do UAC e falhava sem alguém para clicar em Sim (a restauração em Arquivos de Programas também). O CI não pegava:
   o runner do GitHub já é administrador.
   - `instalador/tarefa_atualizacao.ps1` + os três `.iss`: criam a tarefa `<Programa> Atualizacao` (SISTEMA,
     usuários autenticados só podem iniciar: ACE `(A;;GRGX;;;AU)`), a pasta `{commonappdata}\<Programa>\atualizacao`
     (users-modify) e apagam a tarefa ao desinstalar.
   - `src/atualizacao/tarefa.py`: lado do operador (`preparar_pedido`, `script_espera`, `pedir_ao_windows`) e lado do
     SISTEMA (`ler_pedido` confere assinatura, edição, versão mais nova, tamanho e SHA-256; `preparar_aplicacao`
     copia para pasta do SISTEMA, guarda o programa, grava o `aplicar.cmd`; `aplicar_como_sistema`).
   - `src/app.py`: `--aplicar-atualizacao`; `--confirmar-atualizacao ... --sem-banco` (o SISTEMA não abre o banco do
     operador; a abertura seguinte confirma em `conferir_tentativa`).
   - `cliente.disparar_instalacao`: tenta a tarefa; sem ela, caminho antigo (`_disparar_com_administrador`).
     O pacote assinado vai ao lado do .exe baixado (`<arquivo>.json`).
2. **Tentativa falha parava tudo em silêncio.** `CHAVE_RESULTADO` guarda o que houve; `conferir_tentativa` (abertura),
   `falha_pendente`, `aviso()` com `falha`; menu e janela de Atualizações mostram; `painel_envio` manda
   `atualizacao_travada`; a central (`saude_das_lojas`, `central_web/app.js`) mostra o selo "Atualização travada".
3. **Fechava o PDV em uso.** `motivo_automatico`: também espera fila de impressão vazia e 10 min após o fechamento do
   turno. Abertura com instalação disparada não abre a tela (`ui_qt/aviso_atualizando.py`).
4. **Render dormindo.** Timeout de leitura 60 s; sem resposta, `CHAVE_FALHA_CONSULTA` e nova tentativa em 15 min.
5. Pacote de outra edição recusado (`pacote_valido`); `sem_pacote()` dá o motivo certo (antes "assinatura_invalida"
   quando a nuvem só dizia "em dia" ou "pausada").

## Validação

- `tests/test_atualizacao_tarefa.py` (24 casos) e os testes de atualização existentes; central com o selo.
- CI do Windows (`build-windows.yml`, job do WillPDV): depois de instalar, confere que a tarefa existe, aponta
  para o programa instalado, aceita usuário comum e recusa um pedido sem assinatura (roda de verdade como SISTEMA).
- **Não testado:** atualização real num PC sem administrador, com antivírus e UAC padrão. Roteiro abaixo.

## Antes de reativar a oferta (Render: PDV_ATUALIZACAO_PAUSADA=1 continua)

1. Instalar esta versão à mão num caixa de teste (cria a tarefa). Conferir no Agendador de Tarefas.
2. Publicar uma versão de teste maior, tirar a pausa só para esse teste e deixar o caixa sem turno aberto 10 min.
3. Confirmar: sem janela de administrador, o programa fecha, instala, reabre na versão nova, e
   `%ProgramData%\WillPDV\atualizacao\resultado-*.txt` diz `instalada`.
4. Repetir com o instalador corrompido (deve sair `recusada`) e ver o selo na central.
5. Só então tirar a pausa e subir `PDV_ATUALIZACAO_CLIENTE_MINIMO` para esta versão.

## Pendências

- Antigravity: revisar a linha nova em `backend/central_fornecedor.py` e `central_web/app.js`.
- Caixas instalados antes desta versão precisam do instalador manual uma última vez.
- Tutoriais seguintes (grupo e subgrupo, operador com senha, cliente) continuam pendentes.
