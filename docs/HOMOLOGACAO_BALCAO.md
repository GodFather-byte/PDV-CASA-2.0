# Homologação da entrega no balcão

Este é o roteiro para os equipamentos reais. Os testes automatizados não preenchem sua aprovação.
Registre responsável, data, versão/commit, Windows, modelo do iPhone, versão do iOS/Safari,
modelo/conexão da impressora e observações. Comece com backup e banco de demonstração isolado.

| Caso | Ação | Resultado esperado | Estado inicial |
|---|---|---|---|
| iPhone | Abrir o porteiro no Safari por HTTPS, tocar em Instalar, seguir Compartilhar → Adicionar à Tela de Início | Ícone correto, abertura como app; botão de instalação oculto dentro do app | Pendente em aparelho real |
| Sessão do porteiro | Entrar com loja/PIN, fechar e reabrir o ícone; consultar comanda paga e com saldo | Sessão válida ou nova solicitação de PIN; nenhuma liberação com saldo | Pendente em aparelho real |
| Wi-Fi e 4G | Alternar rede e comparar horário do retrato com o caixa | Origem/idade visíveis; falha não mostra saldo antigo como consulta atual | Pendente em aparelho real |
| Leitor e pagamento | Bipar produto, receber dinheiro com troco e dividir por item | Um lançamento por leitura, total/troco corretos e item não pago duas vezes | Pendente em equipamento real |
| Impressão e gaveta | Imprimir um cupom de teste; desligar somente a impressora durante outro envio | Fila preservada; envio incerto exige conferência humana antes de reimprimir; gaveta conforme configuração | Pendente em equipamento real |
| Nuvem sem conexão | Interromper a conexão no banco de demonstração, vender e devolver; restabelecer a conexão | Caixa continua; fila mostra pendências e depois esvazia, sem duplicar UUIDs | Pendente em equipamento real |
| Devolução com estoque | Vender 3 itens e devolver 1 com retorno; devolver outro sem retorno | Bruto preservado, reembolso e estoque corretos; custo recuperado somente com retorno | Pendente em equipamento real |
| Reinício | Fechar/reabrir o PDV de demonstração durante uma fila pendente | Venda, turno e fila preservados; entrega retomada sem duplicação | Pendente em equipamento real |
| Restauração | Testar restauração isolada de backup pelo utilitário | Integridade, vínculos e total de cupons conferidos; original preservado | Pendente em equipamento real |
| Atualização | Instalar a entrega sobre uma instalação de demonstração anterior e abrir o banco | Dados preservados, backup de migração criado e esquema 33 | Pendente em equipamento real |

Não corte a energia do caixa de produção para testar. Para ensaio de queda elétrica, use uma estação e banco
de demonstração, em janela combinada com o responsável, e compare a recuperação com o backup.

Para a parte automatizada, sem hardware, rode:

```bash
python -m src.homologacao relatorio-homologacao.json
python -m unittest tests.test_painel_melhorias tests.test_verificar_nuvem tests.test_qt_estado_nuvem
node --test tests/test_porteiro_instalacao.cjs
```

O primeiro comando usa banco fictício descartável. Os testes de interrupção usam outro processo e outro arquivo;
nenhum deles deve ser apontado para o banco em uso. Guarde o relatório e a execução do CI com o registro manual.
