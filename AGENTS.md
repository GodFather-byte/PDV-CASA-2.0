# WillPDV: instruções para agentes

Fonte única de instruções para qualquer agente (Claude Code, Codex, Antigravity, Copilot).
O `CLAUDE.md` só aponta para cá. Mantenha este arquivo curto: o que é estado do trabalho vai
em `.ai/HANDOFF.md`, o que é localização vai em `.ai/MAPA.md`.

## Ao começar

1. Leia `.ai/HANDOFF.md` (onde o trabalho parou).
2. Leia `.ai/MAPA.md` só se precisar localizar algo.
3. Não leia `README.md` nem `docs/COORDENACAO.md` inteiros: são longos (manual do usuário e
   histórico). Abra só a seção que a tarefa pede.

## Ao terminar

Reescreva `.ai/HANDOFF.md` (substitua, não acumule; o histórico fica no git) e faça commit
junto com o trabalho. Se mudou pasta, ponto de entrada ou comando, ajuste `.ai/MAPA.md`.

## Rodar e testar

```
python -m src.app                          # abre o PDV (Windows: iniciar_pdv.bat)
python -m licenciador.app                  # abre o gerador de licenças
python -m unittest discover -s tests       # suíte inteira
python -m unittest tests.test_caixa        # um arquivo só (prefira isto durante o trabalho)
```

## Erros do caixa

O caixa grava a exceção localmente e sobe no lote da nuvem (não é uma chamada à parte). Para ver o que já chegou, sem imprimir token, senha ou a URL do banco:

```
python scripts/ver_erros_caixa.py --loja CHAVE --desde 2026-11-01 --nivel error --limit 20
```

A fonte é `PDV_API_URL` + `PDV_API_TOKEN` (rota `GET /v1/admin/erros-caixa`) ou, se a API não estiver definida, `PDV_NUVEM_DB_URL` / `DATABASE_URL`. Não cole segredo no comando nem no relatório: o script também filtra a saída.

Python 3.10+. A interface do PDV é **somente Qt (PySide6)**; não há mais Tk no PDV. O gerador de licenças
(`licenciador/`) continua em Tkinter. No Linux os testes de tela precisam de X virtual (ou `QT_QPA_PLATFORM=offscreen`): `xvfb-run -a -s "-screen 0 1920x1080x24" python -m unittest discover -s tests`.
O CI (`.github/workflows/testes.yml`) roda em Windows e Linux, Python 3.10 e 3.12.

## Convenções obrigatórias

- **Dinheiro é inteiro em centavos** (`preco_cent = 350` é R$ 3,50). Nunca `float`.
- **Quantidades** são float com até 4 casas.
- **Datas** em texto ISO local: `YYYY-MM-DD HH:MM:SS`.
- **Venda é identificada por `uuid`** (v4), gerado no PDV.
- Cupom (`cupom`) só existe depois que a venda é fechada ou cancelada.
- O único fluxo de venda é o `CaixaController`.
- Coluna ou tabela nova: migração em `src/database/esquema.py` (`VERSAO_ESQUEMA`, `MIGRACOES`).
- Toda regra nova entra com teste em `tests/`.
- Código, comentários e mensagens em português.

## Quem é dono de quê

| Área | Dono | Observação |
|------|------|-----------|
| `src/core/`, `src/database/` | Claude | Esquema SQLite, formatação, segurança, licença. |
| `src/controllers/` | Claude | Regras de negócio. |
| `src/ui_qt/` | Claude | Telas Qt (PySide6). |
| `backend/` | Antigravity | API na nuvem (FastAPI). |
| `src/sync/sincronizador.py` | Antigravity | Cliente HTTP. |
| Qualquer área, quando chamado | Codex | Reserva: testes, mudança mecânica, diagnóstico e revisão de diff. Não decide regra de negócio. |

Regra de ouro: **não sobrescrever arquivo inteiro de outro dono**; edição pontual apenas.
Antes de criar um arquivo, confira se ele já existe. Pedido para outro dono: escreva em
"Pendências" no `.ai/HANDOFF.md`.

## Trabalho em dupla (Claude Code + Codex)

- Quem conversa com o dono é o **titular**: planeja e decide. O outro é o **reserva**.
- O reserva recebe tarefa fechada, responde em poucas linhas com `arquivo:linha` e nunca
  chama outro agente.
- Vale delegar: localizar algo em código desconhecido, diagnosticar saída grande de teste,
  escrever testes para código existente, mudança mecânica em muitos arquivos, revisar diff.
- Não vale delegar: tarefa de até 3 arquivos, decisão de regra de negócio.
- Licença e segurança (`src/core/licenca.py`, `ed25519.py`, `seguranca.py`, `licenciador/`,
  `tools/gerar_licenca.py`): o titular escreve, o reserva só revisa o diff.
- Revisão cruzada olha só o diff (`git diff main...HEAD`), em uma rodada.
- Um escritor por vez no mesmo arquivo.
