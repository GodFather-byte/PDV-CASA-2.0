# Mapa do repositório

O repositório gera dois programas Windows: **WillPDV** (o PDV do cliente) e **WillPDV Licenças**
(gerador de licenças, só do fornecedor). Python + SQLite local; Tkinter completo e Qt em migração.
PostgreSQL fica na nuvem, sem dependência de internet para vender no caixa.

## Pontos de entrada

| Comando | O que abre |
|---|---|
| `python -m src.app` | PDV (`--sync`: segundo plano com a nuvem; `--autoteste`: autoteste) |
| `python -m src.app --qt` / `--tk` | Prévia PySide6/Qt ou interface Tk completa; mesma base SQLite |
| `python -m src.app --autoteste-qt [arquivo]` | Autoteste Qt isolado, sem dados reais |
| `python -m licenciador.app` | Gerador de licenças |
| `python -m tools.gerar_licenca` | Licenças pela linha de comando (`novo-par`, `emitir`, `ver`) |
| `python -m uvicorn backend.main:app` | API da nuvem |
| `python -m backend.lojas` / `backend.atualizacoes` | Lojas, assinatura e versões na nuvem |
| `python -m backend.lojas cobranca` | Vínculos Asaas e conciliação das mensalidades |
| `python -m backend.worker_asaas` | Processamento durável de webhooks e conciliação periódica |
| `python build_pdv.py` / `build_licenciador.py` | Executável (PyInstaller) e instalador (Inno Setup) |

## Pastas

| Pasta | O que tem |
|---|---|
| `src/core/` | Dinheiro e datas (`formatacao.py`), licença Ed25519 (`licenca.py`, `ed25519.py`), senhas (`seguranca.py`), erros de negócio (`erros.py`), comanda e mesa (`posicao.py`), log (`registro.py`), base dos relatórios (`relatorio.py`), instância única (`instancia.py`) |
| `src/database/` | `esquema.py` (tabelas, migrações e histórico de produtos separado do catálogo), `conexao.py`, `protecao.py` (integridade e backup), `sementes.py` (dados iniciais) |
| `src/controllers/` | Regras de negócio, um arquivo por assunto (lista abaixo) |
| `src/ui/` | Telas Tkinter: `app.py` (janela principal), `caixa_ui.py` (caixa), `painel_mesas.py` (cartões, busca e abas das comandas), `caixa_tema.py` (cores e estilos do caixa), `paleta.py` (modo claro/escuro: as paletas e a troca), `login.py`, `tema.py` e uma tela por módulo |
| `src/ui_qt/` | Migração PySide6/Qt: login, caixa, cadastros, estoque operacional, relatórios, configurações, máquinas, acessos, Telegram e utilitários; escopo em `docs/INTERFACE_QT.md` |
| `src/hardware/` | Impressora térmica ESC/POS e gaveta, balança, logotipo no cupom, impressoras do Windows |
| `src/sync/` | `sincronizador.py`, `licenca_nuvem.py`, `atualizacoes.py`, `telegram_api.py` |
| `licenciador/` | `nucleo.py` (regras), `tela.py` (janela), `app.py`, `autoteste.py` |
| `backend/` | FastAPI: `main.py` (rotas), `lojas.py`, `atualizacoes.py`, `database.py`, `cobrancas.py` (Asaas), `operacao_asaas.py` e `worker_asaas.py` (fila, agenda e indicadores) |
| `tools/` | `gerar_licenca.py`, `gerar_logos.py` (não vão no instalador do PDV) |
| `instalador/` | Scripts Inno Setup (`WillPDV.iss`, `WillLicencas.iss`) e imagens |
| `tests/` | Um `test_*.py` por assunto; `base.py` (banco em memória, relógio controlável); `ui_robo.py` (robô das janelas modais) |
| `docs/` | Guias por assunto (lista abaixo) |
| `.github/workflows/` | `testes.yml` (suíte) e `build-windows.yml` (instaladores) |

## Onde fica cada regra (`src/controllers/`)

| Assunto | Arquivo |
|---|---|
| Venda, itens, pagamento, mesas e comandas | `caixa_controller.py` |
| Turno, numeração de cupom, fechamento | `turno_controller.py`, `conferencia_turno.py` |
| Comissão das garotas | `comissao_controller.py`, `relatorio_comissoes.py` |
| Estoque (baixa, estorno, composição) | `estoque_controller.py` |
| Produtos e importação por planilha | `produto_controller.py`, `importacao_produtos.py` |
| Cadastros e entidades | `cadastro_controller.py`, `entidades.py` |
| Operadores e níveis de acesso | `acesso_controller.py` |
| Configurações da loja | `config_controller.py` (padrões em `CONFIG_PADRAO`, `src/database/sementes.py`) |
| Caderneta (venda a prazo) e contas | `caderneta_controller.py`, `contas_controller.py` |
| Entrega | `entrega_controller.py` |
| Módulos de operação configuráveis (Configurações > Módulos: liga/desliga por tipo de negócio) | convenção em `config_controller.py` (`MODULOS_OPCIONAIS`); ver `docs/ESPECIFICACAO.md` |
| Perfil do estabelecimento (boate, bar, restaurante, churrascaria, comércio: liga os módulos de uma vez) | `perfil_controller.py` (`PERFIS`) · UI `config_ui.escolher_perfil`, `cadastro_loja_ui.py` (primeiro acesso) |
| Códigos especiais do caixa (comissão 50, saída 1002) e o módulo de cada um | `config_controller.py` (`CODIGOS_ESPECIAIS`, `codigo_especial`) |
| Adega: balcão Tk/Qt, cadastro pelo leitor, "6*", fardo/caixa, natural/gelada, atacado por temperatura, cascos e agrupamento | `caixa_controller.py` (`adicionar_item`, `_reprecificar_balcao`), `entidades.py` (seção Adega e `_validar_adega`), `produto_controller.py` (`cadastrar_rapido`, `criar_embalagem`, `embalagem`), `estoque_controller.py` (fardo vira unidades); UI `caixa_ui.py`, `adega_dialogos.py`, `cadastro_rapido_ui.py`, `ui_qt/caixa.py`, `ui_qt/cadastros.py`; guia em `docs/ESTOQUE.md` |
| Pré-pago (recarga, crédito, devolução da sobra) | `caixa_controller.py` (`recarregar`, `saldo_prepago`, `_conferir_credito`, `liquidar`/`fechar`) · UI `caixa_ui.recarga` |
| Cozinha/Bar (setores de impressão, status de preparo por item) | `preparo_controller.py`, `impressao_controller.py` (`setor_do_subgrupo`) · UI `cozinha_ui.py` |
| Impressão e fila | `impressao_controller.py`, `fila_impressao_controller.py`, `impressao_assistente.py` |
| Relatórios | `relatorio_controller.py`, `relatorio_vendas.py`, `relatorio_gestao.py` |
| Telegram do dono | `telegram_controller.py`, `telegram_textos.py`, `notificacoes.py` |
| Backup, limpeza e utilitários | `utilitario_controller.py` |
| Backup externo criptografado e cofre DPAPI | `utilitario_controller.py`, `src/core/backup_seguro.py` |
| Auditoria estruturada e consulta protegida | `auditoria_controller.py`, triggers/migração em `src/database/esquema.py` |

## Documentação (`docs/`)

`ESPECIFICACAO.md` (o que o sistema deve fazer), `INSTALAR_E_TESTAR.md`, `LICENCIADOR.md`,
`NUVEM.md`, `TELEGRAM.md`, `IMPRESSORA.md`, `ESTOQUE.md`, `IMPORTAR_PRODUTOS.md`, `PILOTO.md`,
`COBRANCA_LICENCAS_ASAAS.md` (cobrança e renovação mensal), `COORDENACAO.md` (histórico de pedidos entre agentes).
`BACKUP_EXTERNO.md` (pasta sincronizada, senha e recuperação), `AUDITORIA.md`,
`INTERFACE_QT.md` (prévia e homologação), `TERCEIROS_QT.md` (licenças das dependências).

## Dados

Banco padrão `loja_offline.db` na raiz (no executável: `%LOCALAPPDATA%\WILL-PDV`); outro
arquivo pela variável `PDV_DB`. Bancos, `.env`, `config.ini` e `*.key` nunca vão para o git.
