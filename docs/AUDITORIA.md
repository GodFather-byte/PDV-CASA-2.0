# Auditoria estruturada local

O SQLite local, a partir do esquema **18**, guarda **`auditoria_eventos`**,
separado do `log_eventos` legado.
O PostgreSQL de licenças não participa desse fluxo. Não há envio de auditoria
para serviços externos nem alteração do modelo de um único caixa.

## Eventos e transações

Cada mutação efetiva auditada guarda:

- `id`, `quando` em ISO local `YYYY-MM-DD HH:MM:SS`;
- `operador_id` da sessão e `origem` (`operador` ou `sistema`);
- `entidade` (tabela) e `entidade_id` textual; vendas usam seu **UUID**;
- `acao`, `antes` e `depois` (JSON; cadastro tem antes nulo, exclusão tem depois nulo).

As ações são `cadastro`, `alteracao`, `exclusao`, `preco_alterado`,
`desconto_alterado`, `venda_cancelada`, `item_cancelado`,
`estoque_alterado`, `permissao_alterada` e `credencial_alterada`.
Um UPDATE que altera vários campos recebe a ação específica prioritária, mas
seus retratos conservam todos os campos permitidos. Recalcular uma venda pode
gerar alterações legítimas adicionais; não há cópia automática do log legado.

Os gatilhos cobrem cadastros, composições, permissões, vendas/itens,
lançamentos/itens de estoque e saldos de produtos. O espelho
`produtos_historico` não duplica eventos de produtos vivos; ajustes de saldo
de produtos excluídos continuam auditados. Movimentos de estoque já possuem
histórico próprio: não são duplicados como outro evento de saldo.
Atualizações sem mudança não geram evento. A instalação de sementes e as
migrações de versões antigas não fabricam histórico retroativo.

Gatilhos executam na **mesma transação SQLite** da mutação: erros de integridade,
rollback externo e rollback de savepoint desfazem também os eventos. Não são
gravadas tentativas malsucedidas nesse histórico. O log legado mantém seu
comportamento. A aplicação de desconto recalcula e grava seus valores finais,
com o log legado, em uma única transação. Troca de credencial e a primitiva de
movimento de estoque também revertem seus registros associados em caso de falha.

## Identidade e integração de telas

`Contexto.operador` vincula automaticamente o operador atual ao banco; atribuir
`None` encerra o vínculo. `contexto.auditoria` cria o controller da sessão atual.
Integrações sem `Contexto` devem chamar:

```python
banco.definir_operador_auditoria(operador.id)  # sessão autenticada
# ... operações dos controllers ...
banco.definir_operador_auditoria(None)         # saída da sessão
```

O responsável armazenado num registro, o parâmetro de um controller ou a senha
de supervisor **não substituem** a identidade da sessão. Sem sessão vinculada,
o evento fica explicitamente com origem `sistema` e operador nulo.
Uma conexão `BancoDados` representa uma sessão local; não deve ser compartilhada
por sessões concorrentes. As funções SQLite de auditoria são registradas pela
conexão do PDV; ferramentas externas devem abrir o banco por `BancoDados` para
escrever nas tabelas auditadas. Leitura e a API SQLite de backup não exigem isso.

## Consulta administrativa

```python
AuditoriaController(banco, operador).listar(
    inicio="2026-10-01", fim="2026-10-31",
    acao="preco_alterado", limite=100, offset=0,
)
# Ou: contexto.auditoria.listar(...)
```

Retorna `list[dict]`, com `antes`/`depois` já convertidos em dicionários ou
`None`, na ordem `quando DESC, id DESC`. Datas ISO aceitam dia ou instante com
segundos; início/fim são inclusivos (fim com apenas dia inclui até 23:59:59).
Filtros são opcionais e parametrizados. `limite`: inteiro de 1 a 500, padrão
100; `offset`: inteiro não negativo. Offset além do resultado retorna lista vazia.

É necessário operador **ativo, nível 4 (administrador)** e acesso ao módulo
existente `rel_auditoria`. O controller relê o cadastro a cada consulta: objetos
de sessão antigos ou forjados não mantêm privilégios revogados. O relatório
legado de auditoria por operadores permanece independente e inalterado.

## Privacidade e limites

Retratos usam lista positiva de campos operacionais. Não incluem senha, hash,
token, configuração, dados de licença, nome de cliente/operador/fornecedor,
CPF/CNPJ, contato, endereço, observações e motivos livres de cancelamento.
Mudanças em campos pessoais ou credenciais produzem evento sem seus valores.
IDs internos são mantidos para correlação; valores monetários continuam
inteiros em centavos e quantidades mantêm a precisão existente.

Não há remoção nem retenção automática: exclusões de cadastros não removem
eventos, e backups locais incluem a auditoria. Esse histórico **não é prova
criptográfica nem proteção contra edição direta do arquivo SQLite**. O controle
de consulta é da aplicação; proteger arquivo e backups continua obrigatório.

## Migração e validação

A migração incremental 17 → 18 cria tabela, índices e gatilhos de forma
transacional, sem reescrever cadastros/logs. Reabertura é idempotente.
`BancoDados` mantém o backup verificado anterior à migração.

```text
python -m unittest tests.test_auditoria_estruturada
```

Os testes cobrem privacidade, sessão/supervisor, acesso administrativo,
paginação/filtros, dinheiro em centavos, preço/promoção, desconto, cancelamentos,
estoque, exclusão, savepoints, rollback e migração com sucesso/falha.
