# Handoff (19/11/2026): correções do exe, RustDesk e telas que cabem (branch `correcoes-rustdesk-janelas`)

A publicar: 1.14.18 (1.14.17 nos caixas). **Nuvem religada em 19/11**: o serviço do Render estava ligado a uma cópia
do repositório no Cursor e republicava o commit antigo; agora a origem é o repositório público do GitHub
(`GodFather-byte/PDV-CASA-2.0`, ramo `main`). Nesse modo o Render não publica sozinho a cada push: quem publica é o
workflow "Nuvem: testar e publicar", pelo Deploy Hook com o commit testado.

## O que entrou
- **Falha do exe (PySide 6.12 + Nuitka)**: sinal do Qt ligado direto a método de classe que não é QObject soltava a
  função a cada conexão desfeita; depois de algumas trocas de operador, sair do PDV chamava outra função
  (`TypeError ... unexpected keyword argument 'confirmar'` na Casa Verde e na Resenha, 1.14.9). `ui_qt/sinais.py`
  (`ligar_metodo`) e `ui_qt/app.py`. `tests/test_qt_sinais.py` varre o código e reprova ligação direta nova; o
  `--autoteste-qt` do exe confere que nenhuma função perdeu referência.
- **Treino dentro do exe** pedia licença ("Nenhuma licença ativada"): `turnos.abrir(..., treino=True)` só vale no
  banco de treino em memória.
- **RustDesk**: Utilitários → "Suporte remoto (RustDesk)" abre o programa, lê o ID (`--get-id`), copia e guarda; o ID
  sobe no retrato do caixa e aparece no suporte da central. Sem RustDesk instalado, oferece o site oficial.
- **Telas cortadas**: caixa de 1024 a 1600 de largura sem nada cortado (abas das mesas em 2 linhas, colunas Código e
  Un. somem quando o nome do produto ficaria espremido, quartos em 1 fileira em tela baixa); listas largas deixam o
  nome elástico e quebram títulos em linhas; fechamento do turno cabe sem rolagem em 1366x768; linhas de muitos
  botões quebram (`tema.LinhaFluida`). Medidor: `python -m tools.capturar_telas --largura 1366 --altura 728 --conferir`.
- **Nuvem**: o Deploy Hook vai com `&ref=<commit>` (404 na hora se o Render estiver ligado ao repositório errado) e
  `tools/verificar_nuvem.py` diz qual commit a nuvem continua servindo.

## Limites conhecidos
- Em 1024 de largura, a lista de produtos (12 colunas), a de estoque e a de NF-e ainda rolam de lado.
- A validação no exe desta árvore final fica com o CI (`--autoteste-qt`); no sandbox foi feita na versão anterior às
  mudanças de tela. `tests.test_central_ui` e `tests.test_licenciador` não rodam no sandbox (sem Tkinter).
- `backend/central_fornecedor.py` e `backend/central_web/app.js` (Antigravity) receberam edição pontual: campo
  `rustdesk_id` no suporte.

## Pendências
- Dono: `ANTHROPIC_API_KEY` no Render; instalar na Casa Verde.
- Ideias aprovadas para depois: servidor próprio do RustDesk, sugestão de compra (Will Adega), etiquetas com código
  de barras. Backlog: homologação NFC-e DeliciOz; IBS/CBS 2027; mensalidade EA; tamanho dos backups no Neon.
