"""Esquema SQLite do PDV (a versão atual está em VERSAO_ESQUEMA; as migrações, em MIGRACOES).

Convencoes: dinheiro em INTEIRO de centavos (colunas *_cent); quantidades REAL;
datas em texto ISO local. Booleanos sao INTEGER 0/1.
"""


VERSAO_ESQUEMA = 20

PRODUTOS_HISTORICO_DDL = """CREATE TABLE IF NOT EXISTS produtos_historico (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    subgrupo_id INTEGER NOT NULL REFERENCES subgrupos(id),
    unidade_id INTEGER NOT NULL REFERENCES unidades(id),
    controla_estoque INTEGER NOT NULL DEFAULT 0,
    estoque_minimo REAL NOT NULL DEFAULT 0,
    qt_atual REAL NOT NULL DEFAULT 0,
    ult_preco_cent INTEGER NOT NULL DEFAULT 0,
    custo_cent INTEGER NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1,
    excluido_em TEXT
)"""
_CAMPOS_HISTORICO = ("id", "codigo", "nome", "subgrupo_id", "unidade_id", "controla_estoque",
                     "estoque_minimo", "qt_atual", "ult_preco_cent", "ativo")
_COLUNAS_HISTORICO = ", ".join(_CAMPOS_HISTORICO)
_SINCRONIZAR_HISTORICO = (
    f"INSERT INTO produtos_historico ({_COLUNAS_HISTORICO}) "
    f"VALUES ({', '.join('NEW.' + c for c in _CAMPOS_HISTORICO)}) "
    f"ON CONFLICT(id) DO UPDATE SET {', '.join(c + '=excluded.' + c for c in _CAMPOS_HISTORICO if c != 'id')};")

# Definição única da tabela de máquinas (reutilizada na migração v2). Sem CHECK em
# modo_impressao: a validação fica em config_controller, e isso permite novos modos
# (como 'termica') sem precisar recriar a tabela a cada modo novo.
MAQUINAS_DDL = """CREATE TABLE IF NOT EXISTS maquinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal INTEGER NOT NULL UNIQUE DEFAULT 1,
    nome_computador TEXT, descricao TEXT,
    modo_impressao TEXT NOT NULL DEFAULT 'tela',
    colunas_fita INTEGER NOT NULL DEFAULT 40,
    impressora_remota_pasta TEXT,
    balanca TEXT NOT NULL DEFAULT 'Nenhuma',
    balanca_porta TEXT,
    gaveta INTEGER NOT NULL DEFAULT 0,
    leitor_optico INTEGER NOT NULL DEFAULT 0,
    impressora_termica_conexao TEXT NOT NULL DEFAULT 'rede',
    impressora_termica_endereco TEXT,
    impressora_termica_codepage TEXT NOT NULL DEFAULT 'cp850',
    impressora_termica_cortar INTEGER NOT NULL DEFAULT 1,
    impressora_termica_gaveta INTEGER NOT NULL DEFAULT 0,
    impressora_termica_pino INTEGER NOT NULL DEFAULT 0,
    impressora_remota_conexao TEXT NOT NULL DEFAULT 'pasta',
    impressora_remota_endereco TEXT,
    impressora_termica_logotipo INTEGER NOT NULL DEFAULT 0
)"""

TABELAS = [
    PRODUTOS_HISTORICO_DDL,
    # ------------------------------------------------------------ infraestrutura
    """CREATE TABLE IF NOT EXISTS config (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS loja (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        razao_social TEXT, nome_fantasia TEXT, slogan TEXT, cnpj TEXT, ie TEXT,
        endereco TEXT, complemento TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
        telefone TEXT, email TEXT, logotipo TEXT
    )""",
    MAQUINAS_DDL,
    """CREATE TABLE IF NOT EXISTS acessos (
        modulo TEXT PRIMARY KEY,
        descricao TEXT NOT NULL,
        grupo TEXT NOT NULL,
        nivel INTEGER NOT NULL CHECK (nivel BETWEEN 1 AND 4)
    )""",
    """CREATE TABLE IF NOT EXISTS log_eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quando TEXT NOT NULL,
        operador_id INTEGER,
        evento TEXT NOT NULL,
        detalhe TEXT
    )""",
    # ------------------------------------------------------------------ cadastros
    """CREATE TABLE IF NOT EXISTS unidades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        abreviatura TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS grupos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS subgrupos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        grupo_id INTEGER NOT NULL REFERENCES grupos(id),
        impressora_remota INTEGER NOT NULL DEFAULT 0,
        setor_impressao_id INTEGER REFERENCES setores_impressao(id),
        rodizio_incluso INTEGER NOT NULL DEFAULT 0,
        figura TEXT,
        UNIQUE (grupo_id, nome)
    )""",
    """CREATE TABLE IF NOT EXISTS aliquotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT NOT NULL UNIQUE,
        aliquota REAL NOT NULL DEFAULT 0,
        formato TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL UNIQUE,
        subgrupo_id INTEGER NOT NULL REFERENCES subgrupos(id),
        unidade_id INTEGER NOT NULL REFERENCES unidades(id),
        aliquota_id INTEGER REFERENCES aliquotas(id),
        preco_cent INTEGER NOT NULL DEFAULT 0,
        cobrar_servico INTEGER NOT NULL DEFAULT 1,
        venda INTEGER NOT NULL DEFAULT 1,
        aceita_decimal INTEGER NOT NULL DEFAULT 0,
        atalho TEXT,
        cbarra TEXT,
        controla_estoque INTEGER NOT NULL DEFAULT 0,
        estoque_minimo REAL NOT NULL DEFAULT 0,
        qt_atual REAL NOT NULL DEFAULT 0,
        qt_inicial REAL NOT NULL DEFAULT 0,
        ult_preco_cent INTEGER NOT NULL DEFAULT 0,
        ult_atualizacao TEXT,
        partes INTEGER NOT NULL DEFAULT 1 CHECK (partes BETWEEN 1 AND 55),
        maior INTEGER NOT NULL DEFAULT 1,
        montagem INTEGER NOT NULL DEFAULT 0,
        para_ser_montado INTEGER NOT NULL DEFAULT 0,
        manual INTEGER NOT NULL DEFAULT 0,
        compoe INTEGER NOT NULL DEFAULT 1,
        composto INTEGER NOT NULL DEFAULT 0,
        usa_observacao INTEGER NOT NULL DEFAULT 0,
        comissao_pct REAL NOT NULL DEFAULT 0,
        promo_de TEXT, promo_ate TEXT, promo_preco_cent INTEGER NOT NULL DEFAULT 0,
        sem_inicial INTEGER, sem_final INTEGER, sem_preco_cent INTEGER NOT NULL DEFAULT 0,
        hora_ini TEXT, hora_fim TEXT, hora_preco_cent INTEGER NOT NULL DEFAULT 0,
        validade_dias INTEGER NOT NULL DEFAULT 0,
        balanca INTEGER NOT NULL DEFAULT 0,
        automatico INTEGER NOT NULL DEFAULT 0,
        texto_sugestao TEXT,
        ncm TEXT, desc_aliq_icms TEXT, situacao_tributaria TEXT,
        aliquota_ipi REAL NOT NULL DEFAULT 0, reducao_base REAL NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_produtos_cbarra ON produtos(cbarra) WHERE cbarra IS NOT NULL AND cbarra <> ''",
    "CREATE INDEX IF NOT EXISTS ix_produtos_subgrupo ON produtos(subgrupo_id)",
    """CREATE TABLE IF NOT EXISTS observacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo INTEGER NOT NULL UNIQUE,
        texto TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS composicoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
        insumo_id INTEGER NOT NULL REFERENCES produtos(id),
        quantidade REAL NOT NULL CHECK (quantidade > 0),
        UNIQUE (produto_id, insumo_id)
    )""",
    """CREATE TABLE IF NOT EXISTS cargos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS operadores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
        senha TEXT NOT NULL,
        nivel INTEGER NOT NULL DEFAULT 0 CHECK (nivel BETWEEN 0 AND 4),
        cargo_id INTEGER REFERENCES cargos(id),
        garcom INTEGER NOT NULL DEFAULT 0,
        entregador INTEGER NOT NULL DEFAULT 0,
        vendedor INTEGER NOT NULL DEFAULT 0,
        recebe_comissao INTEGER NOT NULL DEFAULT 0,
        comissao_pct REAL NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS fornecedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        contato TEXT, ddd TEXT, telefone TEXT, celular TEXT, cnpj TEXT, ie TEXT,
        endereco TEXT, complemento TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
        email TEXT, obs TEXT,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS bairros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        taxa_cent INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_consulta TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        endereco TEXT, complemento TEXT, cep TEXT, codigo TEXT,
        bairro_id INTEGER REFERENCES bairros(id),
        cidade TEXT, telefone TEXT, rg TEXT, cpf TEXT, email TEXT, obs TEXT,
        limite_cent INTEGER NOT NULL DEFAULT 0,
        saldo_cent INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    "CREATE INDEX IF NOT EXISTS ix_clientes_nome ON clientes(nome)",
    """CREATE TABLE IF NOT EXISTS tipos_pagamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL UNIQUE,
        ordem INTEGER NOT NULL DEFAULT 0,
        caixa INTEGER NOT NULL DEFAULT 1,
        emite_vale INTEGER NOT NULL DEFAULT 0,
        permite_troco INTEGER NOT NULL DEFAULT 0,
        na_gaveta INTEGER NOT NULL DEFAULT 1,
        saldo_inicial_cent INTEGER NOT NULL DEFAULT 0,
        taxa_pct REAL NOT NULL DEFAULT 0,
        desc_cartao_pct REAL NOT NULL DEFAULT 0,
        vias INTEGER NOT NULL DEFAULT 1,
        tipo_tef INTEGER NOT NULL DEFAULT 0,
        aciona_tef INTEGER NOT NULL DEFAULT 0,
        cheque_tef INTEGER NOT NULL DEFAULT 0,
        mais_info INTEGER NOT NULL DEFAULT 0,
        acrescimo_cent INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS planos_contas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        codigo TEXT NOT NULL UNIQUE,
        debito INTEGER NOT NULL DEFAULT 1,
        resultado INTEGER NOT NULL DEFAULT 1,
        ordem INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS subplanos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        plano_id INTEGER NOT NULL REFERENCES planos_contas(id),
        UNIQUE (plano_id, nome)
    )""",
    # -------------------------------------------------------------------- contas
    """CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subplano_id INTEGER NOT NULL REFERENCES subplanos(id),
        descricao TEXT NOT NULL,
        tipo_pagamento_id INTEGER NOT NULL REFERENCES tipos_pagamento(id),
        valor_cent INTEGER NOT NULL,
        documento TEXT, mercadoria INTEGER NOT NULL DEFAULT 0, nota TEXT,
        previsao INTEGER NOT NULL DEFAULT 0,
        dt_entrada TEXT NOT NULL, dt_vencimento TEXT NOT NULL, dt_quitacao TEXT,
        fornecedor_id INTEGER REFERENCES fornecedores(id),
        transferir_para_id INTEGER REFERENCES tipos_pagamento(id),
        lancamento_estoque_id INTEGER,
        parcela TEXT,
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_contas_venc ON contas(dt_vencimento)",
    # ------------------------------------------------------------------- estoque
    """CREATE TABLE IF NOT EXISTS lancamentos_estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL CHECK (tipo IN
            ('inicial','pedido','compra','entrada','saida','descarte','contagem','desc_acabados')),
        data TEXT NOT NULL,
        descricao TEXT, documento TEXT, nota_fiscal TEXT,
        fornecedor_id INTEGER REFERENCES fornecedores(id),
        valor_cent INTEGER NOT NULL DEFAULT 0,
        desconto_cent INTEGER NOT NULL DEFAULT 0,
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS itens_estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lancamento_id INTEGER NOT NULL REFERENCES lancamentos_estoque(id) ON DELETE CASCADE,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        quantidade REAL NOT NULL,
        preco_unit_cent INTEGER NOT NULL DEFAULT 0,
        desconto_cent INTEGER NOT NULL DEFAULT 0,
        valor_cent INTEGER NOT NULL DEFAULT 0,
        qt_anterior REAL NOT NULL DEFAULT 0,
        diferenca REAL NOT NULL DEFAULT 0,
        aplicado INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS movimentos_estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        tipo TEXT NOT NULL,
        quantidade REAL NOT NULL,
        qt_apos REAL NOT NULL,
        ref_tipo TEXT, ref_id INTEGER,
        criado_em TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_movest_prod ON movimentos_estoque(produto_id, criado_em)",
    # ------------------------------------------------------------- caixa / vendas
    """CREATE TABLE IF NOT EXISTS turnos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero INTEGER NOT NULL,
        terminal INTEGER NOT NULL DEFAULT 1,
        operador_id INTEGER REFERENCES operadores(id),
        aberto_em TEXT NOT NULL,
        valor_inicial_cent INTEGER NOT NULL DEFAULT 0,
        cupom_inicial INTEGER NOT NULL DEFAULT 0,
        fechado_em TEXT,
        valor_final_cent INTEGER,
        cupom_final INTEGER,
        esperado_cent INTEGER,
        resultado_cent INTEGER,
        fechado_por INTEGER REFERENCES operadores(id),
        status TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto','fechado'))
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_turno_aberto ON turnos(terminal) WHERE status = 'aberto'",
    """CREATE TABLE IF NOT EXISTS vendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        cupom INTEGER,
        turno_id INTEGER REFERENCES turnos(id),
        terminal INTEGER NOT NULL DEFAULT 1,
        operador_id INTEGER REFERENCES operadores(id),
        modalidade TEXT NOT NULL DEFAULT 'balcao'
            CHECK (modalidade IN ('balcao','mesa','caderneta','entrega')),
        posicao INTEGER NOT NULL DEFAULT 0,
        comanda INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'aberta'
            CHECK (status IN ('aberta','conta_enviada','fechada','cancelada')),
        aberta_em TEXT NOT NULL,
        ultimo_lancamento_em TEXT,
        fechada_em TEXT,
        pessoas INTEGER NOT NULL DEFAULT 0,
        garcom_id INTEGER REFERENCES operadores(id),
        vendedor_id INTEGER REFERENCES operadores(id),
        entregador_id INTEGER REFERENCES operadores(id),
        cliente_id INTEGER REFERENCES clientes(id),
        subtotal_cent INTEGER NOT NULL DEFAULT 0,
        desconto_cent INTEGER NOT NULL DEFAULT 0,
        desconto_pct REAL NOT NULL DEFAULT 0,
        servico_cent INTEGER NOT NULL DEFAULT 0,
        servico_manual INTEGER NOT NULL DEFAULT 0,
        rodizio INTEGER NOT NULL DEFAULT 0,
        rodizio_total_cent INTEGER NOT NULL DEFAULT 0,
        taxa_cent INTEGER NOT NULL DEFAULT 0,
        acrescimo_cent INTEGER NOT NULL DEFAULT 0,
        total_cent INTEGER NOT NULL DEFAULT 0,
        pago_cent INTEGER NOT NULL DEFAULT 0,
        troco_cent INTEGER NOT NULL DEFAULT 0,
        vale_cent INTEGER NOT NULL DEFAULT 0,
        troco_para_cent INTEGER NOT NULL DEFAULT 0,
        mensagem TEXT,
        apelido TEXT,
        saida_entrega_em TEXT,
        cancelada_por INTEGER REFERENCES operadores(id),
        motivo_cancelamento TEXT,
        sincronizado INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_vendas_cupom ON vendas(cupom) WHERE cupom IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_vendas_status ON vendas(status, modalidade)",
    "CREATE INDEX IF NOT EXISTS ix_vendas_fechada ON vendas(fechada_em)",
    "CREATE INDEX IF NOT EXISTS ix_vendas_sync ON vendas(sincronizado)",
    """CREATE TABLE IF NOT EXISTS itens_venda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        quantidade REAL NOT NULL,
        preco_unit_cent INTEGER NOT NULL,
        total_cent INTEGER NOT NULL,
        cobra_servico INTEGER NOT NULL DEFAULT 1,
        observacao TEXT,
        comissao_cent INTEGER NOT NULL DEFAULT 0,
        partes INTEGER NOT NULL DEFAULT 1,
        cancelado INTEGER NOT NULL DEFAULT 0,
        cancelado_em TEXT,
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT NOT NULL,
        status_preparo TEXT NOT NULL DEFAULT 'pendente',
        preparo_atualizado_em TEXT,
        preparo_operador_id INTEGER REFERENCES operadores(id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_itens_venda ON itens_venda(venda_id)",
    """CREATE TABLE IF NOT EXISTS itens_venda_partes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES itens_venda(id) ON DELETE CASCADE,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        fracao REAL NOT NULL
    )""",
    # turno_id (v9): turno em que o dinheiro entrou. O adiantamento de uma mesa conta nesse turno, mesmo que a conta
    # feche no seguinte. Fica NULL só no pagamento antigo de uma mesa ainda aberta, que conta no turno da venda.
    """CREATE TABLE IF NOT EXISTS pagamentos_venda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        tipo_pagamento_id INTEGER NOT NULL REFERENCES tipos_pagamento(id),
        valor_cent INTEGER NOT NULL,
        troco_cent INTEGER NOT NULL DEFAULT 0,
        criado_em TEXT NOT NULL,
        turno_id INTEGER REFERENCES turnos(id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_pagto_venda ON pagamentos_venda(venda_id)",
    """CREATE TABLE IF NOT EXISTS movimentos_caixa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turno_id INTEGER NOT NULL REFERENCES turnos(id),
        tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
        valor_cent INTEGER NOT NULL CHECK (valor_cent > 0),
        descricao TEXT,
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS repiques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turno_id INTEGER NOT NULL REFERENCES turnos(id),
        venda_id INTEGER REFERENCES vendas(id),
        posicao INTEGER NOT NULL DEFAULT 0,
        valor_cent INTEGER NOT NULL CHECK (valor_cent > 0),
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS caderneta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL REFERENCES clientes(id),
        venda_id INTEGER REFERENCES vendas(id),
        tipo TEXT NOT NULL CHECK (tipo IN ('debito','credito')),
        valor_cent INTEGER NOT NULL CHECK (valor_cent > 0),
        descricao TEXT,
        criado_em TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_caderneta_cli ON caderneta(cliente_id)",
    # Setores de impressão (v19): impressoras remotas nomeadas (cozinha, bar...), para o módulo de operação
    # Cozinha/Bar (usar_cozinha_bar). Sem CHECK em conexao: mesmo motivo do modo_impressao acima.
    """CREATE TABLE IF NOT EXISTS setores_impressao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        conexao TEXT NOT NULL DEFAULT 'pasta',
        pasta TEXT,
        endereco TEXT,
        ativo INTEGER NOT NULL DEFAULT 1,
        ordem INTEGER NOT NULL DEFAULT 0
    )""",
    # Fila de impressão (v5): o que vai para a impressora térmica/remota é gravado aqui e enviado por uma thread,
    # então a impressora fora do ar não trava o caixa e nenhum cupom se perde. `dados` são os bytes ESC/POS prontos.
    """CREATE TABLE IF NOT EXISTS fila_impressao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT NOT NULL,
        destino TEXT NOT NULL DEFAULT 'caixa' CHECK (destino IN ('caixa','remota')),
        tipo TEXT,
        nome TEXT NOT NULL,
        dados BLOB NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','enviado','erro','cancelado')),
        tentativas INTEGER NOT NULL DEFAULT 0,
        proxima_tentativa TEXT,
        ultimo_erro TEXT,
        enviado_em TEXT,
        venda_id INTEGER,
        setor_id INTEGER REFERENCES setores_impressao(id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_fila_status ON fila_impressao(status, destino, id)",
    # Telegram do dono (v11): `telegram_chats` são as conversas autorizadas (quem digitou o código de pareamento no bot);
    # `telegram_fila` são os avisos esperando envio (gravados na hora, enviados por uma thread: a internet fora do ar não
    # trava o caixa e o aviso sai quando voltar). `entregue_a` guarda os chats que já receberam (para não repetir).
    """CREATE TABLE IF NOT EXISTS telegram_chats (
        chat_id INTEGER PRIMARY KEY,
        nome TEXT,
        criado_em TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS telegram_fila (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT NOT NULL,
        tipo TEXT,
        texto TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','enviado','erro')),
        tentativas INTEGER NOT NULL DEFAULT 0,
        entregue_a TEXT NOT NULL DEFAULT '',
        ultimo_erro TEXT,
        enviado_em TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_telegram_fila ON telegram_fila(status, id)",
    # Comissão das garotas (v7): o código 50 do caixa marca a comissão no número da garota (o mesmo da comanda dela).
    # Não é venda: não entra em faturamento nem estoque. Fica 'pendente' até ser paga (sai dinheiro do caixa) ou cancelada.
    """CREATE TABLE IF NOT EXISTS garotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero INTEGER NOT NULL UNIQUE CHECK (numero BETWEEN 1 AND 99999),
        nome TEXT NOT NULL,
        observacao TEXT,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS comissoes_garotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        garota INTEGER NOT NULL CHECK (garota BETWEEN 1 AND 99999),
        valor_cent INTEGER NOT NULL CHECK (valor_cent > 0),
        turno_id INTEGER REFERENCES turnos(id),
        operador_id INTEGER REFERENCES operadores(id),
        observacao TEXT,
        criado_em TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','paga','cancelada')),
        paga_em TEXT,
        pago_por INTEGER REFERENCES operadores(id),
        pago_turno_id INTEGER REFERENCES turnos(id),
        movimento_id INTEGER REFERENCES movimentos_caixa(id),
        cancelada_em TEXT,
        cancelada_por INTEGER REFERENCES operadores(id),
        motivo_cancelamento TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_comissoes_garota ON comissoes_garotas(garota, status)",
    "CREATE INDEX IF NOT EXISTS ix_comissoes_criado ON comissoes_garotas(criado_em)",
    "CREATE INDEX IF NOT EXISTS ix_comissoes_turno ON comissoes_garotas(turno_id)",
    # Acerto da garota (v12): cada pagamento a ela guarda a comissão paga, os shows lançados pelo operador (quantidade e valor de
    # cada um) e o total entregue. Shows nunca são contados sozinhos: só existem quando o operador digita no fechamento dela.
    """CREATE TABLE IF NOT EXISTS acertos_garotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        garota INTEGER NOT NULL CHECK (garota BETWEEN 1 AND 99999),
        turno_id INTEGER REFERENCES turnos(id),
        operador_id INTEGER REFERENCES operadores(id),
        criado_em TEXT NOT NULL,
        comissao_cent INTEGER NOT NULL DEFAULT 0,
        shows_qtd INTEGER NOT NULL DEFAULT 0,
        show_valor_cent INTEGER NOT NULL DEFAULT 0,
        shows_cent INTEGER NOT NULL DEFAULT 0,
        total_cent INTEGER NOT NULL,
        movimento_id INTEGER REFERENCES movimentos_caixa(id),
        tirou_do_caixa INTEGER NOT NULL DEFAULT 0,
        pix_cent INTEGER NOT NULL DEFAULT 0,
        vale_cent INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_acertos_garota ON acertos_garotas(garota, criado_em)",
    "CREATE INDEX IF NOT EXISTS ix_acertos_turno ON acertos_garotas(turno_id)",
    # Índices dos relatórios e do fechamento (v3). São criados também em bancos antigos, na próxima abertura.
    "CREATE INDEX IF NOT EXISTS ix_vendas_status_fechada ON vendas(status, fechada_em)",
    "CREATE INDEX IF NOT EXISTS ix_vendas_cliente ON vendas(cliente_id, status, fechada_em)",
    "CREATE INDEX IF NOT EXISTS ix_vendas_turno ON vendas(turno_id)",
    "CREATE INDEX IF NOT EXISTS ix_itens_produto ON itens_venda(produto_id)",
    "CREATE INDEX IF NOT EXISTS ix_partes_item ON itens_venda_partes(item_id)",
    "CREATE INDEX IF NOT EXISTS ix_pagto_tipo ON pagamentos_venda(tipo_pagamento_id)",
    "CREATE INDEX IF NOT EXISTS ix_movcaixa_turno ON movimentos_caixa(turno_id)",
    "CREATE INDEX IF NOT EXISTS ix_repiques_turno ON repiques(turno_id)",
    "CREATE INDEX IF NOT EXISTS ix_caderneta_venda ON caderneta(venda_id)",
    "CREATE INDEX IF NOT EXISTS ix_movest_ref ON movimentos_estoque(ref_tipo, ref_id)",
    "CREATE INDEX IF NOT EXISTS ix_itens_estoque_lanc ON itens_estoque(lancamento_id)",
    "CREATE INDEX IF NOT EXISTS ix_itens_estoque_prod ON itens_estoque(produto_id)",
    "CREATE INDEX IF NOT EXISTS ix_lanc_estoque_data ON lancamentos_estoque(data)",
    "CREATE INDEX IF NOT EXISTS ix_contas_quit ON contas(dt_quitacao)",
]

# As relações históricas não dependem da permanência do cadastro comercial.
_TABELAS_HISTORICAS = ("itens_venda", "itens_venda_partes", "itens_estoque", "movimentos_estoque")
TABELAS = [
    sql.replace("REFERENCES produtos(id)", "REFERENCES produtos_historico(id)")
    if any(sql.startswith(f"CREATE TABLE IF NOT EXISTS {t} (") for t in _TABELAS_HISTORICAS) else sql
    for sql in TABELAS
]
TABELAS += [
    f"CREATE TRIGGER IF NOT EXISTS produtos_historico_inserir AFTER INSERT ON produtos BEGIN {_SINCRONIZAR_HISTORICO} END",
    f"CREATE TRIGGER IF NOT EXISTS produtos_historico_atualizar AFTER UPDATE ON produtos BEGIN {_SINCRONIZAR_HISTORICO} END",
]


def _migracao_historico_produtos() -> list[str]:
    comandos = [
        f"INSERT OR IGNORE INTO produtos_historico ({_COLUNAS_HISTORICO}) SELECT {_COLUNAS_HISTORICO} FROM produtos",
        "UPDATE produtos_historico SET custo_cent = ult_preco_cent",
        "CREATE TEMP TABLE _excluidos_v17 AS SELECT id FROM produtos "
        "WHERE instr(codigo, '~') > 0 AND substr(codigo, instr(codigo, '~') + 1) = CAST(id AS TEXT)",
        "CREATE TEMP TABLE _sequencias_v17 AS SELECT name, seq FROM sqlite_sequence",
        "CREATE TEMP TABLE _partes_v17 AS SELECT * FROM itens_venda_partes",
        "DROP TABLE itens_venda_partes",
    ]
    for tabela in ("itens_venda", "itens_estoque", "movimentos_estoque"):
        ddl = next(sql for sql in TABELAS if sql.startswith(f"CREATE TABLE IF NOT EXISTS {tabela} ("))
        nova = f"_{tabela}_v17"
        comandos += [
            ddl.replace(f"IF NOT EXISTS {tabela} (", f"{nova} (", 1),
            f"INSERT INTO {nova} SELECT * FROM {tabela}",
            f"DROP TABLE {tabela}",
            f"ALTER TABLE {nova} RENAME TO {tabela}",
        ]
    comandos += [
        next(sql for sql in TABELAS if sql.startswith("CREATE TABLE IF NOT EXISTS itens_venda_partes (")),
        "INSERT INTO itens_venda_partes SELECT * FROM _partes_v17",
        "DROP TABLE _partes_v17",
        "UPDATE sqlite_sequence SET seq = MAX(seq, COALESCE((SELECT seq FROM _sequencias_v17 s "
        "WHERE s.name = sqlite_sequence.name), seq))",
        "INSERT INTO sqlite_sequence(name, seq) SELECT s.name, s.seq FROM _sequencias_v17 s "
        "WHERE s.name IN ('itens_venda', 'itens_venda_partes', 'itens_estoque', 'movimentos_estoque') "
        "AND NOT EXISTS (SELECT 1 FROM sqlite_sequence atual WHERE atual.name = s.name)",
        "DROP TABLE _sequencias_v17",
        "UPDATE produtos_historico SET codigo = substr(codigo, 1, instr(codigo, '~') - 1), "
        "nome = CASE WHEN substr(nome, -length(' (excluído ' || id || ')')) = ' (excluído ' || id || ')' "
        "THEN substr(nome, 1, length(nome) - length(' (excluído ' || id || ')')) ELSE nome END, "
        "ativo = 0, excluido_em = datetime('now', 'localtime') WHERE id IN (SELECT id FROM _excluidos_v17)",
        "DELETE FROM composicoes WHERE produto_id IN (SELECT id FROM _excluidos_v17) "
        "OR insumo_id IN (SELECT id FROM _excluidos_v17)",
        "DELETE FROM produtos WHERE id IN (SELECT id FROM _excluidos_v17)",
        "DROP TABLE _excluidos_v17",
    ]
    comandos += [sql for sql in TABELAS if sql.startswith("CREATE INDEX") or sql.startswith("CREATE UNIQUE INDEX")]
    return comandos

# Índices que dependem de colunas criadas por migrações: rodam DEPOIS delas (ver BancoDados._criar_esquema),
# senão um banco antigo falharia ao criar o índice de uma coluna que ainda não existe.
INDICES_POS_MIGRACAO = [
    # Uma mesa OU uma comanda aberta por número: a comanda 2 e a mesa 2 podem existir ao mesmo tempo (v4).
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_posicao_aberta ON vendas(comanda, posicao)
        WHERE modalidade = 'mesa' AND status IN ('aberta','conta_enviada')""",
    "CREATE INDEX IF NOT EXISTS ix_pagto_turno ON pagamentos_venda(turno_id)",     # v9
]

# Lista positiva: campos livres, contatos, documentos e credenciais nunca viram
# retratos. As colunas omitidas podem disparar o evento, mas não são serializadas.
_AUDITORIA_CAMPOS = {
    "produtos": ("id codigo nome subgrupo_id unidade_id preco_cent ativo controla_estoque "
                 "estoque_minimo qt_atual qt_inicial ult_preco_cent promo_de promo_ate promo_preco_cent "
                 "sem_inicial sem_final sem_preco_cent hora_ini hora_fim hora_preco_cent "
                 "cobrar_servico venda aceita_decimal partes maior montagem composto comissao_pct").split(),
    "produtos_historico": "id qt_atual custo_cent ativo excluido_em".split(),
    "unidades": "id nome abreviatura".split(),
    "grupos": "id nome".split(),
    "subgrupos": "id nome grupo_id impressora_remota".split(),
    "aliquotas": "id aliquota formato".split(),
    "observacoes": "id codigo".split(),
    "composicoes": "id produto_id insumo_id quantidade".split(),
    "cargos": "id".split(),
    "operadores": ("id nivel cargo_id garcom entregador vendedor recebe_comissao comissao_pct ativo").split(),
    "fornecedores": "id ativo".split(),
    "bairros": "id taxa_cent".split(),
    "clientes": "id bairro_id limite_cent saldo_cent ativo".split(),
    "garotas": "id numero ativo".split(),
    "tipos_pagamento": ("id tipo ordem caixa emite_vale permite_troco na_gaveta saldo_inicial_cent "
                        "taxa_pct desc_cartao_pct acrescimo_cent ativo").split(),
    "planos_contas": "id codigo debito resultado ordem".split(),
    "subplanos": "id plano_id".split(),
    "acessos": "modulo nivel".split(),
    "vendas": ("id uuid cupom turno_id status subtotal_cent desconto_cent desconto_pct servico_cent "
               "taxa_cent acrescimo_cent total_cent pago_cent cancelada_por").split(),
    "itens_venda": ("id venda_id produto_id quantidade preco_unit_cent total_cent cancelado cancelado_em").split(),
    "lancamentos_estoque": ("id tipo data fornecedor_id valor_cent desconto_cent").split(),
    "itens_estoque": ("id lancamento_id produto_id quantidade preco_unit_cent desconto_cent valor_cent "
                      "qt_anterior diferenca aplicado").split(),
}
_AUDITORIA_OMITIDOS = {
    "produtos": ("atalho cbarra usa_observacao texto_sugestao para_ser_montado manual compoe "
                 "validade_dias balanca automatico ncm desc_aliq_icms situacao_tributaria aliquota_ipi reducao_base").split(),
    "subgrupos": ["figura"],
    "aliquotas": ["descricao"],
    "observacoes": ["texto"],
    "cargos": ["nome"],
    "operadores": ["nome", "senha"],
    "fornecedores": ("nome contato ddd telefone celular cnpj ie endereco complemento bairro cidade uf cep email obs").split(),
    "bairros": ["nome"],
    "clientes": ("numero_consulta nome endereco complemento cep codigo cidade telefone rg cpf email obs").split(),
    "garotas": ["nome", "observacao"],
    "tipos_pagamento": "vias tipo_tef aciona_tef cheque_tef mais_info".split(),
    "planos_contas": ["nome"],
    "subplanos": ["nome"],
}


def _gatilhos_auditoria() -> list[str]:
    comandos = []
    for tabela, campos in _AUDITORIA_CAMPOS.items():
        chave = "modulo" if tabela == "acessos" else "uuid" if tabela == "vendas" else "id"
        def retrato(prefixo):
            pares = ", ".join(f"'{c}', {prefixo}.{c}" for c in campos)
            return f"auditoria_json({pares})"

        def mudou(colunas):
            return " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in colunas)

        alterados = mudou(campos + _AUDITORIA_OMITIDOS.get(tabela, []))
        acao = "'alteracao'"
        if tabela == "produtos":
            precos = [c for c in campos if "preco" in c]
            acao = (f"CASE WHEN {mudou(precos)} THEN 'preco_alterado' "
                    "WHEN OLD.qt_atual IS NOT NEW.qt_atual THEN 'estoque_alterado' ELSE 'alteracao' END")
        elif tabela == "produtos_historico":
            acao = "'estoque_alterado'"
        elif tabela in ("operadores", "acessos"):
            permissoes = ["nivel", "ativo"] if tabela == "operadores" else ["nivel"]
            acao = f"CASE WHEN {mudou(permissoes)} THEN 'permissao_alterada' ELSE 'alteracao' END"
            if tabela == "operadores":
                acao = (f"CASE WHEN {mudou(permissoes)} THEN 'permissao_alterada' "
                        "WHEN OLD.senha IS NOT NEW.senha THEN 'credencial_alterada' ELSE 'alteracao' END")
        elif tabela == "vendas":
            acao = ("CASE WHEN OLD.status IS NOT NEW.status AND NEW.status = 'cancelada' "
                    "THEN 'venda_cancelada' WHEN OLD.desconto_cent IS NOT NEW.desconto_cent "
                    "OR OLD.desconto_pct IS NOT NEW.desconto_pct THEN 'desconto_alterado' ELSE 'alteracao' END")
        elif tabela == "itens_venda":
            acao = ("CASE WHEN OLD.cancelado IS NOT NEW.cancelado AND NEW.cancelado = 1 "
                    "THEN 'item_cancelado' WHEN OLD.preco_unit_cent IS NOT NEW.preco_unit_cent "
                    "THEN 'preco_alterado' ELSE 'alteracao' END")
        for operacao, prefixo, antes, depois, evento in (
            ("INSERT", "NEW", "NULL", retrato("NEW"), "'cadastro'"),
            ("UPDATE", "NEW", retrato("OLD"), retrato("NEW"), acao),
            ("DELETE", "OLD", retrato("OLD"), "NULL", "'exclusao'"),
        ):
            condicao = "auditoria_ativa() = 1"
            if operacao == "UPDATE":
                condicao += f" AND ({alterados})"
            if tabela == "produtos_historico":
                # O espelho de um produto vivo não pode duplicar seu evento.
                if operacao != "UPDATE":
                    continue
                condicao += (f" AND NOT EXISTS (SELECT 1 FROM produtos WHERE id = {prefixo}.id)"
                             " AND OLD.qt_atual IS NOT NEW.qt_atual")
            comandos.append(
                f"CREATE TRIGGER IF NOT EXISTS auditoria_{tabela}_{operacao.lower()} "
                f"AFTER {operacao} ON {tabela} WHEN {condicao} BEGIN "
                "INSERT INTO auditoria_eventos(quando, operador_id, origem, entidade, entidade_id, acao, antes, depois) "
                f"VALUES (auditoria_agora(), auditoria_operador(), "
                f"CASE WHEN auditoria_operador() IS NULL THEN 'sistema' ELSE 'operador' END, "
                f"'{tabela}', CAST({prefixo}.{chave} AS TEXT), {evento}, {antes}, {depois}); END")
    return comandos


AUDITORIA = [
    """CREATE TABLE IF NOT EXISTS auditoria_eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quando TEXT NOT NULL,
        operador_id INTEGER,
        origem TEXT NOT NULL CHECK (origem IN ('sistema', 'operador')),
        entidade TEXT NOT NULL,
        entidade_id TEXT NOT NULL,
        acao TEXT NOT NULL,
        antes TEXT,
        depois TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_auditoria_quando ON auditoria_eventos(quando, id)",
    "CREATE INDEX IF NOT EXISTS ix_auditoria_acao_quando ON auditoria_eventos(acao, quando, id)",
] + _gatilhos_auditoria()


# Migrações por versão de destino, aplicadas em ordem quando o banco está atrasado
# (ver BancoDados._migrar). Bancos novos já nascem na VERSAO_ESQUEMA e não as executam. Cada passo é um
# comando SQL ou ("coluna", tabela, nome, definição), que só adiciona a coluna se ela ainda não existir.
MIGRACOES = {
    # v2: adiciona campos da impressora térmica e remove o CHECK de modo_impressao.
    # Recria a tabela maquinas preservando os dados existentes.
    2: [
        "ALTER TABLE maquinas RENAME TO _maquinas_old",
        MAQUINAS_DDL,
        "INSERT INTO maquinas (id, terminal, nome_computador, descricao, modo_impressao,"
        " colunas_fita, impressora_remota_pasta, balanca, balanca_porta, gaveta, leitor_optico)"
        " SELECT id, terminal, nome_computador, descricao, modo_impressao, colunas_fita,"
        " impressora_remota_pasta, balanca, balanca_porta, gaveta, leitor_optico FROM _maquinas_old",
        "DROP TABLE _maquinas_old",
    ],
    # v3: marca quais formas de pagamento ficam fisicamente na gaveta (o valor esperado do turno passa a
    # contar só elas). Mantém o comportamento antigo (tudo conta) para formas personalizadas e tira da
    # gaveta as eletrônicas: cartão, Pix, transferência e as que acionam TEF.
    3: [
        ("coluna", "tipos_pagamento", "na_gaveta", "INTEGER NOT NULL DEFAULT 1"),
        "UPDATE tipos_pagamento SET na_gaveta = 0 WHERE aciona_tef = 1 OR tipo_tef > 0"
        " OR lower(tipo) LIKE '%cart_o%' OR lower(tipo) LIKE '%pix%' OR lower(tipo) LIKE '%transfer%'",
    ],
    # v4: comandas. Uma comanda é uma venda de modalidade 'mesa' com comanda = 1 (aparece junto das mesas,
    # com serviço, pré-conta e transferência iguais). O índice antigo, único só por posicao, impedia a comanda
    # 2 de coexistir com a mesa 2; o novo (comanda, posicao) é criado em INDICES_POS_MIGRACAO.
    4: [
        ("coluna", "vendas", "comanda", "INTEGER NOT NULL DEFAULT 0"),
        "DROP INDEX IF EXISTS ix_mesa_aberta",
    ],
    # v5: logotipo da loja no cupom térmico. A tabela fila_impressao é criada por TABELAS (IF NOT EXISTS).
    5: [
        ("coluna", "maquinas", "impressora_termica_logotipo", "INTEGER NOT NULL DEFAULT 0"),
    ],
    # v6: comanda por número (até 10 mil). Quem nunca mexeu no limite (ainda 200, o antigo padrão) passa a 10000;
    # a chave posicao_padrao nasce em CONFIG_PADRAO, na abertura seguinte.
    6: [
        "UPDATE config SET valor = '10000' WHERE chave = 'num_comandas' AND valor = '200'",
    ],
    # v7: as tabelas garotas e comissoes_garotas nascem em TABELAS (IF NOT EXISTS); as chaves novas de configuração
    # (codigo_comissao, exigir_senha_comissao) nascem em CONFIG_PADRAO. Nada a migrar.
    7: [],
    # v8: a comissão paga guarda o turno em que foi paga (pago_turno_id). Os bancos que já estavam na v7 criaram a tabela sem essa
    # coluna, então ela é acrescentada; as pagas antigas recebem o turno da sangria do pagamento, quando houve.
    8: [
        ("coluna", "comissoes_garotas", "pago_turno_id", "INTEGER REFERENCES turnos(id)"),
        "UPDATE comissoes_garotas SET pago_turno_id = (SELECT m.turno_id FROM movimentos_caixa m "
        "WHERE m.id = comissoes_garotas.movimento_id) WHERE status = 'paga' AND pago_turno_id IS NULL AND movimento_id IS NOT NULL",
    ],
    # v9: cada pagamento guarda o turno em que foi recebido. Os antigos herdam o turno da venda (o de fechamento ou
    # cancelamento), que era onde já contavam; o de uma mesa ainda aberta fica NULL e continua contando onde ela fechar.
    9: [
        ("coluna", "pagamentos_venda", "turno_id", "INTEGER REFERENCES turnos(id)"),
        "UPDATE pagamentos_venda SET turno_id = (SELECT v.turno_id FROM vendas v WHERE v.id = pagamentos_venda.venda_id)"
        " WHERE turno_id IS NULL",
    ],
    # v10: some a tabela `mesas` do protótipo Flet (apagado). As mesas e comandas são vendas de modalidade 'mesa'.
    10: [
        "DROP TABLE IF EXISTS mesas",
    ],
    # v11: Telegram do dono. As tabelas telegram_chats e telegram_fila nascem em TABELAS (IF NOT EXISTS); as chaves novas de
    # configuração (telegram_*) nascem em CONFIG_PADRAO e o módulo cfg_telegram em ACESSOS, na abertura seguinte. Nada a migrar.
    11: [],
    # v12: acerto da garota com shows. A tabela acertos_garotas nasce em TABELAS (IF NOT EXISTS); as chaves novas de
    # configuração (show_valores, comissao_pede_shows) nascem em CONFIG_PADRAO. Nada a migrar.
    12: [],
    # v13: parte do acerto da garota paga por Pix (a tabela acertos_garotas pode ter nascido na v12 sem a coluna).
    13: [
        ("coluna", "acertos_garotas", "pix_cent", "INTEGER NOT NULL DEFAULT 0"),
    ],
    # v14: acréscimo por forma de pagamento (taxa do cartão de crédito, R$ 5,00 por venda). A forma guarda o valor do
    # acréscimo e a venda guarda o que foi cobrado. As formas de crédito que já existem passam a cobrar R$ 5,00.
    14: [
        ("coluna", "tipos_pagamento", "acrescimo_cent", "INTEGER NOT NULL DEFAULT 0"),
        ("coluna", "vendas", "acrescimo_cent", "INTEGER NOT NULL DEFAULT 0"),
        "UPDATE tipos_pagamento SET acrescimo_cent = 500 WHERE acrescimo_cent = 0"
        " AND (lower(tipo) LIKE '%cart_o%cr_dito%' OR lower(tipo) IN ('crédito', 'credito'))",
    ],
    # v15: nome da comanda ou mesa ("Carlos", "Aniversário"), mostrado no cartão do painel e no título da venda.
    15: [
        ("coluna", "vendas", "apelido", "TEXT"),
    ],
    # v16: vale da garota, descontado da parte do acerto paga por Pix (o dinheiro do vale já saiu antes).
    16: [
        ("coluna", "acertos_garotas", "vale_cent", "INTEGER NOT NULL DEFAULT 0"),
    ],
    17: _migracao_historico_produtos(),
    18: AUDITORIA,
    # v19: módulo de operação Cozinha/Bar (usar_cozinha_bar). A tabela setores_impressao nasce em TABELAS
    # (IF NOT EXISTS); aqui só as colunas aditivas em tabelas que já existiam.
    19: [
        ("coluna", "subgrupos", "setor_impressao_id", "INTEGER REFERENCES setores_impressao(id)"),
        ("coluna", "itens_venda", "status_preparo", "TEXT NOT NULL DEFAULT 'pendente'"),
        ("coluna", "itens_venda", "preparo_atualizado_em", "TEXT"),
        ("coluna", "itens_venda", "preparo_operador_id", "INTEGER REFERENCES operadores(id)"),
        ("coluna", "fila_impressao", "setor_id", "INTEGER REFERENCES setores_impressao(id)"),
    ],
    # v20: módulo de operação Rodízio (usar_rodizio). Cobrança fixa por pessoa, por mesa/comanda;
    # produtos de subgrupo "incluso no rodízio" não entram na conta por item nessas vendas.
    20: [
        ("coluna", "subgrupos", "rodizio_incluso", "INTEGER NOT NULL DEFAULT 0"),
        ("coluna", "vendas", "rodizio", "INTEGER NOT NULL DEFAULT 0"),
        ("coluna", "vendas", "rodizio_total_cent", "INTEGER NOT NULL DEFAULT 0"),
    ],
}
