# HANDOFF

## Entrega atual: PDV só em Qt (Tk removido do PDV)

- **O PDV tem uma única interface, Qt/PySide6.** `python -m src.app` abre o Qt; `--qt`/`--tk` deixaram de existir.
  `src/ui/` (Tk) foi apagado (o git guarda o histórico). `--autoteste` agora confere módulos, bibliotecas
  (Qt/SQLite/SSL) e as telas Qt + backup; `--autoteste-qt` segue como alias (o CI usa).
- **Gerador de licenças (`licenciador/`) continua em Tkinter**, por decisão do dono. Ele levou consigo
  `tema.py`, `icone.py` e `paleta.py` (antes em `src/ui/`); `paleta.py` perdeu as paletas do PDV.
- Peças compartilhadas que ficavam em `src/ui/` foram movidas: `Contexto` -> `src/controllers/contexto.py`,
  leitura de valor do pagamento -> `src/core/valor_pagamento.py`, `entregar_via` -> `comissao_controller.py`.
- Instalador: removido o atalho "WillPDV Qt (prévia)"; o atalho normal já abre o Qt. Janelas Qt ganharam o
  ícone `instalador/willpdv.ico` (`aplicar_icone`).
- **Testes:** os que exercitavam telas Tk foram apagados/podados por script (classes e métodos que citavam
  tkinter/`src.ui`/`ui_robo`); sobraram os de regra, controlador e Qt. Também saíram dois testes de `test_qt_relatorios`
  que comparavam o Qt com o Tk. Cobertura de tela agora é só Qt. Suíte neste ambiente (Python 3.13, Qt offscreen,
  sem tkinter): 2186 testes, 166 ignorados, só falham os 2 de `licenciador` por falta de tkinter nesse Python; no
  Python 3.12 com tkinter + xvfb, `test_licenciador`, `test_central_ui` e `test_empacotamento` passam.
- Docs atualizados: `AGENTS.md`, `.ai/MAPA.md`, `README.md` (partes principais), `INTERFACE_QT.md`,
  `INSTALAR_E_TESTAR.md`. Muitos outros guias em `docs/` ainda citam "Tk/Qt" como histórico.

## Pendências desta mudança

- Homologar o Qt no balcão (teclado, impressora, gaveta, balança, leitor) antes de gerar o novo Setup: a rede
  de segurança do Tk não existe mais.
- Revisão de cobertura (Haiku, só leitura) listou regras que só tinham teste em tela Tk. Já repostas em
  `tests/test_regras_recuperadas.py`: vias do fechamento 1-3, nome da casa obrigatório, alerta de gaveta (Qt).
  Ainda sem teste equivalente confirmado (ver `git show 4e6e6d2 -- tests/`): falha de impressão não duplicar
  devolução; ticket de saída 1002 disparado no pagamento; garota inativa/sem turno no modo comissão; primeiro
  acesso/perfil; exclusão em massa só com a palavra de confirmação; aviso de giro de caixa sem venda.
- Limpar menções "Tk" restantes em `docs/` e comentários do código quando convier.

---

Estado anterior (1.9.0), preservado abaixo:

## Entrega e decisões

- PDV **1.9.0**, licenciador **1.2.0**, esquema **29**. Recursos gerais para
  todos os perfis, nas interfaces Tk e Qt/PySide6; Tk permanece disponível.
- Base publicada: `1962a69` (1.8 e merge do PR #15). Esta entrega é integrada
  diretamente na `main`; usuário autorizou commit, integração e push normal,
  sem force. Não criar merge artificial quando não houver divergência.
- Preservados PBKDF2 de 600 mil iterações com atualização de hashes legados,
  validação de identificadores SQL e cálculo Decimal do serviço.
- Decisões do usuário: devolução parcial/total por cupom, autorização e motivo,
  retorno opcional ao estoque e reembolso explícito; troca é nova venda.
  Fechamento divergente exige justificativa, mas permite fechamento autorizado.
- Telegram: resumo ativo às **23h locais**. Aplicar 23h uma única vez também
  em instalações antigas, preservando alterações posteriores e sem ligar o bot.

## Oito frentes implementadas

1. **Homologação isolada:** `python -m src.app --homologacao [arquivo.json]`,
   também disponível em `python -m src.homologacao`. Banco fictício descartável,
   ignora `PDV_DB`, não usa hardware/rede. Relatório novo, sem sobrescrita.
2. **Recuperação:** mesma venda/UUID e pagamentos confirmados após reabrir;
   rollback transacional comprovado, inclusive encerrando processo filho.
   Fila persiste `enviando` antes do I/O; envio abandonado vira `incerto`,
   bloqueia seu destino e exige conferência humana auditada antes de reenviar.
3. **Backup verificável:** restauração de cópia em pasta temporária, integridade,
   esquema, vínculos e contagens. Reprovação e avisos explícitos e persistidos;
   aprovação com avisos não atualiza a comprovação do backup externo.
   Estado/data do último ensaio nas telas e no painel.
4. **Qt/notebook/teclado:** rolagem de menu e conteúdo, busca `Ctrl+K`,
   ações da fila distribuídas em linhas, telas novas integradas e revalidação
   de acesso ao reabrir. Operação de devolução no caixa exige turno e estado
   pronto, inclusive durante fechamento/gravação.
5. **Fechamento explicativo:** declaração explícita de todas as formas,
   comparação esperado/informado, justificativa de divergências, snapshot e fita.
   Cancelar conferência preserva turno, sem imprimir nem gerar backup.
6. **Devoluções/trocas:** ledger auditado por cupom via `CaixaController`;
   idempotência por UUID, estoque opcional, dinheiro/gaveta, externo declarado
   ou abatimento de caderneta. Relatório por data/turno do reembolso nas duas UIs.
7. **Diagnóstico:** impressora, gaveta, balança e leitor, sem acionar hardware
   na abertura; confirmação explícita, auditoria, permissões revalidadas,
   resultado do comando separado da confirmação física.
8. **Telegram agendado:** pendência persistente, recibos por chat, recuperação
   offline e horário editável Tk/Qt. Resumos incluem reembolsos por sua data,
   preservando bruto original e separando líquido gerencial.

## Esquema, integração e documentação

- Migração **28** cria devoluções, itens e vínculos de trocas, com proteção
  do histórico; **29** reconstrói o CHECK da fila para `enviando`/`incerto`,
  preservando linhas, IDs e sequência. A versão final não é 28.
- Menus principais, operações do caixa, relatórios, alertas e inventário do
  autoteste conectados. Abertura de devoluções no caixa é modal; ao voltar,
  recarrega o balcão para a troca. Novas telas mantêm controle de acesso.
- Guias: [melhorias 1.9](../docs/MELHORIAS_1_9.md),
  [devoluções](../docs/DEVOLUCOES.md),
  [fechamento](../docs/FECHAMENTO_EXPLICATIVO.md); atualizados backup externo,
  impressão, Telegram, interface Qt e mapa de localização.

## Validação final

- Inventário completo coberto **em etapas**: **2821 casos distintos,
  2811 aprovados e 10 ignorados; nenhuma pendência**.
- Primeira tentativa bloqueou numa fixture Tk antiga de fechamento. Corrigida.
  A execução seguinte concluiu 1955 casos antes de o watchdog identificar
  devoluções Qt abrindo sem turno: corrigido o guard e adicionado teste específico.
- Continuação: 979 casos (incluindo regressões repetidas), inicialmente com
  duas fixtures antigas: versão do esquema fixada em 27 e dinheiro de fechamento
  sem descontar comissão paga. Corrigidas para versão atual e R$ 75,00 reais.
- Regressão final: **87 casos, zero erros/falhas**; cobertura dos IDs de todo o
  inventário consolidada com as etapas anteriores. Não alegar uma única execução
  ininterrupta de 2821 casos. Três regressões específicas adicionais passaram.
- CLI público de homologação: cinco cenários aprovados, `ok: true`, saída zero.
  Autoteste inclui **137 módulos** e abertura das novas telas.
- Ambiente: Windows, Python 3.15, Tk 9, SQLite 3.53.4. `compileall` e
  `git diff --check` passaram. Pylance expirou; não alegar type-check completo.
- Logs incluem erros simulados de backup/Telegram e avisos de descarte de
  callbacks Tk; não foram ocultados. Evidências ficam na pasta da sessão,
  fora do repositório; nenhum banco de produção ou segredo real foi utilizado.

## Limites e pendências para produção

- **Não foi gerado novo Setup/ZIP 1.9 nesta entrega.** Portáteis 1.7 são antigos.
  Antes do piloto, empacotar a versão atual e validar uma cópia do banco.
  Outra pasta de instalação não isola `%LOCALAPPDATA%\WILL-PDV`; usar `PDV_DB`
  apontando à cópia e uma interface/instância por banco.
- Devolução não atende pré-pago nem cobrança/itens inclusos de rodízio.
  Externo é declaração, não estorno bancário. Sem crédito de troca automático;
  reembolso mais nova venda. Não verifica saldo físico da gaveta.
- Bruto, CMV e comissões históricos não são estornados automaticamente;
  relatórios deixam isso explícito e não contam duas vezes a saída da gaveta.
- Impressão física não tem garantia exactly-once. Mesmo envio aceito exige
  papel conferido; falhas de transporte comuns ainda podem ser ambíguas.
- Homologar hardware, falta de papel, gaveta, balança, leitor, teclado/escala e
  interrupção controlada na cópia. Automação não certifica queda elétrica real.
- Bot precisa ativo, token e dono pareado; PC desligado não oferece serviço local.
  Central/licenças ainda requerem ensaio real. Preservar a ponte Render/Neon.
- Cobrança automática, Asaas e integrações fiscais não foram ativadas.
  iFood/NFC-e SP seguem sem homologação. Validar nuvem/caixa/celular e
  substituir credenciais anteriormente expostas.
