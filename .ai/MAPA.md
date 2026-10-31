# Mapa do repositório

O repositório gera dois programas Windows: **WillPDV** (o PDV do cliente) e **WillPDV Licenças**
(gerador de licenças, só do fornecedor). Python + SQLite local; interface do PDV só em Qt (PySide6); o gerador de licenças segue em Tkinter.
PostgreSQL fica na nuvem, sem dependência de internet para vender no caixa.

## Pontos de entrada

| Comando | O que abre |
|---|---|
| `python -m src.app` | PDV (`--sync`: segundo plano com a nuvem; `--autoteste`: autoteste). Com o porteiro ligado, a página do celular sobe na rede do caixa e o retrato das comandas abertas vai para a nuvem |
| `python -m src.app --edicao ea_superacoes` | Edição E&A Superações (adega); `iniciar_ea_superacoes.bat` no Windows |
| `python -m src.app --autoteste-qt [arquivo]` | Mesmo autoteste Qt (alias de `--autoteste`) |
| `python -m src.app --homologacao [arquivo.json]` | Cinco cenários de recuperação em banco fictício descartável; sem rede ou hardware |
| `python -m licenciador.app` | Gerador de licenças |
| `python -m licenciador.app --central` | Central Telegram do fornecedor: configuração local e bot; somente no PC exclusivo |
| `python -m licenciador.central_cli` | Administração local da central (subcomando obrigatório; `--help` lista opções) |
| `python -m tools.gerar_licenca` | Licenças pela linha de comando (`novo-par`, `emitir`, `ver`) |
| `python -m uvicorn backend.main:app` | API da nuvem |
| `python -m backend.lojas` / `backend.atualizacoes` | Lojas, assinatura e versões na nuvem |
| `python -m backend.lojas cobranca` | Vínculos Asaas e conciliação das mensalidades |
| `python -m backend.worker_asaas` | Processamento durável de webhooks e conciliação periódica |
| `python -m backend.lojas painel LOJA [senha]` | Senha do painel do dono no celular (app em `/painel/` da nuvem); o dono também a troca no PDV (Configurações > Nuvem) |
| `python -m backend.lojas limpar-painel` | Apaga já o que passou da retenção do painel (vendas > 120 dias, sessões vencidas, caixas parados); a nuvem também faz sozinha |
| `python -m tools.gerar_icones_painel` | Ícones PNG da PWA do painel (só biblioteca padrão) |
| `python build_pdv.py` / `build_licenciador.py` | Executável (PyInstaller) e instalador (Inno Setup); `build_pdv.py --edicao ea_superacoes` gera o E&A Superações |

## Pastas

| Pasta | O que tem |
|---|---|
| `src/core/` | Dinheiro e datas (`formatacao.py`), licença Ed25519 (`licenca.py`, `ed25519.py`), senhas (`seguranca.py`), erros de negócio (`erros.py`), comanda e mesa (`posicao.py`), log (`registro.py`), base dos relatórios (`relatorio.py`), instância única (`instancia.py`) |
| `src/database/` | `esquema.py` (tabelas, migrações e histórico de produtos separado do catálogo), `conexao.py`, `protecao.py` (integridade e backup), `sementes.py` (dados iniciais) |
| `src/controllers/` | Regras de negócio, um arquivo por assunto (lista abaixo) |
| `src/ui_qt/` | Interface do PDV em PySide6/Qt: login, caixa, cadastros, estoque operacional, relatórios, configurações, máquinas, acessos, Telegram e utilitários; escopo em `docs/INTERFACE_QT.md` |
| `src/hardware/` | Impressora térmica ESC/POS e gaveta, balança, logotipo no cupom, impressoras do Windows |
| `src/sync/` | `sincronizador.py`, `licenca_nuvem.py`, `atualizacoes.py`, `telegram_api.py`, `ponte.py` (credencial individual, licença, contato técnico e pedido de renovação), `painel_envio.py` (vendas e retrato de cada caixa para o painel do dono; troca da senha do painel) |
| `src/porteiro/` | Página do porteiro no celular: consulta só de leitura da comanda no caixa (`/porteiro`, Wi-Fi) e retrato das abertas para a nuvem (`nuvem_envio.py`, 4G). A mesma página em `backend/porteiro.py` |
| `licenciador/` | `nucleo.py` (regras), `tela.py` (janela), `app.py`, `autoteste.py`; central própria em `central.py` (SQLite/emissão/ponte), `central_bot.py`, `central_cli.py`, `central_tela.py` |
| `backend/` | FastAPI: `main.py` (rotas), `ponte.py` (central técnica, caixas aprovados e entrega de licenças assinadas), `lojas.py`, `atualizacoes.py`, `database.py`, `cobrancas.py` (Asaas), `operacao_asaas.py` e `worker_asaas.py` (fila, agenda e indicadores), `painel.py` (painel do dono: envio, um retrato por caixa, senha, sessão, consultas e limpeza automática) e `painel_web/` (a PWA servida em `/painel/`) |
| `tools/` | `gerar_licenca.py`, `gerar_logos.py` (não vão no instalador do PDV) |
| `instalador/` | Scripts Inno Setup (`WillPDV.iss`, `WillLicencas.iss`, `EASuperacoes.iss`) e imagens (`ea-superacoes-*`: marca da edição adega) |
| `tests/` | Um `test_*.py` por assunto; `base.py` (banco em memória, relógio controlável); `ui_robo.py` (robô das janelas modais) |
| `docs/` | Guias por assunto (lista abaixo) |
| `.github/workflows/` | `testes.yml` (suíte), `build-windows.yml` (instaladores) e `nuvem-deploy.yml` (testa a nuvem e aciona o deploy no Render) |

## Onde fica cada regra (`src/controllers/`)

| Assunto | Arquivo |
|---|---|
| Venda, itens, pagamento, mesas e comandas | `caixa_controller.py` |
| Cartões de mesas, comandas, garotas e balcão no caixa (visual da boate) | modelo `mesas_modelo.py` (`montar_tiles`); desenho e teclado em `ui_qt/painel_mesas.py`; ligação em `ui_qt/caixa.py` (`carregar_mesas`) |
| Turno, numeração de cupom, fechamento | `turno_controller.py`, `conferencia_turno.py` |
| Edição do programa (WillPDV ou E&A Superações/adega): marca, pasta de dados, perfil fixo, opções escondidas | `src/core/edicao.py`; usada em `ui_qt/app.py`, `ui_qt/configuracoes.py`, `config_controller.salvar_config`, `database/conexao.py` |
| Tela cheia do caixa (Ctrl+F, config `caixa_tela_cheia`) | `ui_qt/caixa.py` (`aplicar_tela_cheia`), `ui_qt/app.py` (`abrir_caixa`) |
| Relógio no topo do caixa (hora, segundos, dia e data) | `ui_qt/relogio.py` (`RelogioCaixa`); estilos `relogio_*` em `ui_qt/caixa.py` |
| Troca de turno no modelo clássico (maquininha, gaveta, confirmação, resumo sobra/falta) | `ui_qt/caixa.py` (`ir_para_fechamento`), `ui_qt/fechamento_turno.py` (`DialogoMaquininha`, `PainelFechamento`) |
| Conferência por forma e justificativa | `ui_qt/fechamento.py`; contrato em `docs/FECHAMENTO_EXPLICATIVO.md` |
| Devolução por cupom e troca auditadas | API única em `caixa_controller.py`, ledger em `devolucoes_controller.py`; `ui_qt/devolucoes.py`; `docs/DEVOLUCOES.md` |
| Comissão das garotas | `comissao_controller.py`, `relatorio_comissoes.py` |
| Estoque (baixa, estorno, composição) | `estoque_controller.py` |
| Reposição por giro de 30 dias, cobertura de 7 dias e etiquetas | `estoque_controller.py`, `etiqueta_controller.py`; telas de estoque e etiquetas Qt |
| Retornáveis por cliente (sem caução automática) | `retornaveis_controller.py`; `ui_qt/retornaveis.py` |
| Promoções e simulação de faixas sem acumular | `promocoes_controller.py`, regras em `produto_controller.py`; `ui_qt/promocoes.py` |
| Alertas operacionais e painel do dono | `alertas_controller.py`, `telegram_controller.py`; `ui_qt/alertas.py` |
| Produtos e importação por planilha | `produto_controller.py`, `importacao_produtos.py` |
| Cadastros e entidades | `cadastro_controller.py`, `entidades.py` |
| Operadores e níveis de acesso | `acesso_controller.py` |
| Configurações da loja | `config_controller.py` (padrões em `CONFIG_PADRAO`, `src/database/sementes.py`) |
| Caderneta (venda a prazo) e contas | `caderneta_controller.py`, `contas_controller.py` |
| Entrega | `entrega_controller.py` |
| Preparação de iFood e NFC-e SP (sem operação) | `integracoes_controller.py`; campos em `config_controller.py`, padrões em `sementes.py`; pendências em Configurações Qt |
| Módulos de operação configuráveis (Configurações > Módulos: liga/desliga por tipo de negócio) | convenção em `config_controller.py` (`MODULOS_OPCIONAIS`); ver `docs/ESPECIFICACAO.md` |
| Perfil do estabelecimento (boate, bar, restaurante, churrascaria, comércio: liga os módulos de uma vez) | `perfil_controller.py` (`PERFIS`) · UI Qt (`ui_qt/configuracoes.py`, primeiro acesso em `ui_qt/app.py`) |
| Códigos especiais do caixa (comissão 50, saída 1002) e o módulo de cada um | `config_controller.py` (`CODIGOS_ESPECIAIS`, `codigo_especial`) |
| Adega: balcão Qt, cadastro pelo leitor, "6*", fardo/caixa, natural/gelada, atacado por temperatura, cascos e agrupamento | `caixa_controller.py` (`adicionar_item`, `_reprecificar_balcao`), `entidades.py` (seção Adega e `_validar_adega`), `produto_controller.py` (`cadastrar_rapido`, `criar_embalagem`, `embalagem`), `estoque_controller.py` (fardo vira unidades); UI `ui_qt/caixa.py`, `ui_qt/cadastros.py`; guia em `docs/ESTOQUE.md` |
| Pré-pago (recarga, crédito, devolução da sobra) | `caixa_controller.py` (`recarregar`, `saldo_prepago`, `_conferir_credito`, `liquidar`/`fechar`) · UI `ui_qt/caixa.py` |
| Cozinha/Bar (setores de impressão, status de preparo por item) | `preparo_controller.py`, `impressao_controller.py` (`setor_do_subgrupo`) · UI |
| Cozinha/Bar em PySide6 | `ui_qt/cozinha.py`; setores em Mais cadastros; navegação por busca em `ui_qt/app.py` |
| Impressão e fila | `impressao_controller.py`, `fila_impressao_controller.py`, `impressao_assistente.py` |
| Recuperação após interrupção e roteiro isolado | `fila_impressao_controller.py` (`enviando`/`incerto`, conferência humana), `src/homologacao.py`; guia `docs/MELHORIAS_1_9.md` |
| Relatórios | `relatorio_controller.py`, `relatorio_vendas.py`, `relatorio_gestao.py` |
| Devoluções por data/turno do reembolso | `relatorio_vendas.py` (`devolucoes`), menus Relatórios > Caixa Qt; bruto histórico preservado |
| Telegram do dono | `telegram_controller.py`, `telegram_textos.py`, `notificacoes.py` |
| Backup, limpeza e utilitários | `utilitario_controller.py` |
| Teste de restauração isolada | `protecao.py` (`testar_restauracao_isolada`), `utilitario_controller.py` (`testar_recuperacao`), `ui_qt/restaurar_backup.py` |
| Diagnóstico de impressora/gaveta/balança/leitor | `diagnostico_controller.py`, `ui_qt/diagnostico.py`; sem teste físico na abertura |
| Backup externo criptografado e cofre DPAPI | `utilitario_controller.py`, `src/core/backup_seguro.py` |
| Auditoria estruturada e consulta protegida | `auditoria_controller.py`, triggers/migração em `src/database/esquema.py` |

## Documentação (`docs/`)

`ESPECIFICACAO.md` (o que o sistema deve fazer), `INSTALAR_E_TESTAR.md`, `LICENCIADOR.md`,
`NUVEM.md`, `TELEGRAM.md`, `IMPRESSORA.md`, `ESTOQUE.md` (inclui as regras da adega), `ADEGA.md` (checklist de
implantação da adega), `IMPORTAR_PRODUTOS.md`, `PILOTO.md`,
`COBRANCA_LICENCAS_ASAAS.md` (cobrança e renovação mensal), `PAINEL_DONO.md` (painel do dono no celular), `PORTEIRO.md` (porteiro no celular, Wi-Fi e 4G),
`COORDENACAO.md` (histórico de pedidos entre agentes).
`BACKUP_EXTERNO.md` (pasta sincronizada, senha e recuperação), `AUDITORIA.md`,
`CENTRAL_TELEGRAM.md` (configuração dos dois painéis Telegram e central local com API como ponte; sem cobrança),
`INTERFACE_QT.md` (prévia e homologação), `TERCEIROS_QT.md` (licenças das dependências).

## Dados

Banco padrão `loja_offline.db` na raiz (no executável: `%LOCALAPPDATA%\WILL-PDV`); outro
arquivo pela variável `PDV_DB`. Bancos, `.env`, `config.ini` e `*.key` nunca vão para o git.
Logotipos importados ficam em `identidade/` junto ao banco; validação e preview compartilhados
em `src/core/identidade_visual.py`. Configuração e limites em `docs/ADEGA.md`.
