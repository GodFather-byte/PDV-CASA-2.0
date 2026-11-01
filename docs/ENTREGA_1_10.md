# Entrega 1.10.0 — painel financeiro e operação da nuvem

## Devoluções

- O painel mantém o bruto das vendas fechadas e mostra separadamente devoluções e líquido dos dados recebidos.
- A devolução entra no **dia operacional do reembolso**, mesmo que a venda original seja de outro dia.
  Um dia só com devoluções pode ter líquido negativo. Troca é devolução mais uma venda nova.
- A venda, os pagamentos e o ledger original continuam preservados. Cada devolução sobe por UUID;
  repetição confirma o mesmo evento e conteúdo diferente com o mesmo UUID é recusado.
- Registros acima da retenção da nuvem são confirmados sem armazenar novamente. O arquivo completo permanece no PDV.
- Dados de caixas antigos ou com pendências mostram aviso de informação incompleta. Atualize a nuvem antes dos caixas.

## Custos e comissões

- Vendas fechadas na versão 1.10.0 guardam custo calculado no fechamento, incluindo composição, fardo e divisão em partes.
  Alterar o custo do cadastro depois não altera essa referência.
- O custo recuperado pela devolução exige retorno ao estoque e um produto com baixa de estoque.
  Produto descartado, serviço sem baixa e item que não voltou ao estoque não recuperam custo.
- Cupons antigos não ganham um custo inventado: sem registro histórico, o painel sinaliza valores de custo parciais.
- Devoluções parciais rateiam custo e comissão dos itens pela quantidade acumulada, com soma exata em centavos.
- **Ajuste de comissão é referência para conferência do gerente.** Não desconta salário, não altera comissão paga,
  não debita a gaveta e não faz estorno bancário. Comissões de garotas, shows e acertos continuam independentes dos itens.
- O relatório CMV já existente mantém seu critério de custo atual. A referência congelada desta entrega é usada
  nos ajustes de devolução apresentados no painel; não reescreve relatórios nem acertos antigos.
- As restrições anteriores de devolução de pré-pago/rodízio continuam vigentes (`DEVOLUCOES.md`).

## Sincronização leve e estado da fila

- O modo rápido continua olhando mudanças a cada 5 segundos com o PDV aberto, mas o envio ao Neon
  sai em lote (padrão 15 minutos), na hora no fechamento do turno, ou quando o celular pede.
- Um contador transacional identifica alterações nos dados que alimentam o painel, em qualquer conexão SQLite.
  O retrato só é recalculado quando os dados mudam ou o dia operacional vira.
- O envio compara a assinatura do retrato. Lotes seguintes levam somente vendas/devoluções pendentes.
  Sem mudanças e com a loja parada, não há batimento: o banco pode dormir.
- Reinício do processo, alteração do destino ou perda do retrato remoto exigem um envio completo.
  Servidores antigos recebem retrato completo; devoluções sem confirmação continuam na fila.
- A barra inferior do caixa mostra estado, quantidade de vendas e devoluções pendentes e último envio confirmado.
  A visão geral também mostra esses dados. Falha da API não é tratada como prova de ausência de internet no PC.

## Organização e dependências

- CaixaController continua a entrada única. `caixa_divisao.py` guarda a divisão por itens;
  `caixa_totais.py` guarda o cálculo de totais; `custos_venda.py` guarda custo e rateio.
- Os arquivos `.in` guardam faixas de manutenção; os `.txt` contêm versões exatas e hashes.
  Aplicação, backend, testes e ferramenta de build usam arquivos próprios.
- CI, Render e geração dos instaladores instalam com `--require-hashes`.
- Para atualizar, use uv 0.12.23, execute os comandos abaixo e valide a matriz Windows/Linux e Python 3.10/3.12:

```bash
uv pip compile requirements.in --python-version 3.10 --universal --generate-hashes -o requirements.txt
uv pip compile backend/requirements.in --python-version 3.10 --universal --generate-hashes -o backend/requirements.txt
uv pip compile requirements-build.in --python-version 3.10 --universal --generate-hashes -o requirements-build.txt
uv pip compile requirements-test.in --python-version 3.10 --universal --generate-hashes -o requirements-test.txt
```

## Publicação

- `render.yaml` declara publicação automática por commit da branch conectada.
  Essa configuração deve estar aplicada ao serviço no Render; editar o arquivo não comprova a configuração da conta.
- O workflow pode acionar `RENDER_DEPLOY_HOOK_URL`, quando configurado, ou aguardar o deploy automático pelo Git.
- A verificação consulta `/v1/versao` e exige o SHA esperado de `RENDER_GIT_COMMIT`. Saúde HTTP 200 sozinha não confirma deploy.
- O endereço padrão é `https://willpdv-nuvem-6sp0.onrender.com`; `PDV_NUVEM_URL` pode substituí-lo nas variáveis do repositório.
- Falta de publicação gera falha na verificação. A conta da hospedagem ainda precisa estar acessível para corrigir
  branch conectada, deploy automático ou hook, se necessário.

## Banco e homologação

Esquema 33: confirmações de devoluções, custo por item e contador de revisão. São tabelas aditivas,
sem backfill financeiro. Há backup antes da migração. Reiniciar uma versão antiga em banco 33 é recusado;
uma reversão exige o procedimento de restauração apropriado.

Testes automatizados de interrupção de processo não equivalem a queda elétrica real. A homologação em iPhone,
impressora, gaveta, leitor e PC do balcão segue o roteiro em `HOMOLOGACAO_BALCAO.md`.
