# Handoff — mais tutoriais guiados, para leigos e idosos (12/11/2026)

Branch `mais-tutoriais`, criada da main depois do #88 (Pix integrado). Pedido do dono: mais tutoriais para o sistema
ficar fácil até para quem nunca usou computador.

## O que foi feito

- `controllers/tutoriais.py`: `ROTEIROS` com 7 tutoriais (produto, grupo, subgrupo, operador, cliente, forma de
  pagamento, fornecedor), textos em linguagem simples, condição nova `escolhido` (lista de opções).
- `ui_qt/tutorial.py`: motor geral `iniciar(principal, chave)`; balão com letra grande, contraste alto, "Passo X de N",
  botão Próximo destacado e uma dica dizendo o que falta quando ele está apagado.
- `ui_qt/cadastros.py`: tutorial que não é de produto conclui ao salvar um registro novo (`tutorial_chave`).
- `ui_qt/app.py`: um botão por tutorial no grupo Tutoriais, com ✓ no que o operador já concluiu. Some se a casa não
  usa o cadastro (ex.: clientes sem caderneta nem delivery) e fica apagado sem acesso.
- Testes em `tests/test_tutorial_guiado.py` (alvos nas 3 edições, balões em 1024x600, fluxo do subgrupo inteiro).

## Para criar outro tutorial de cadastro

Escreva os passos e registre em `ROTEIROS`. O alvo é o `objectName` do campo (`produto_<campo>` em qualquer cadastro).

## Próximos (ainda não feitos)

- Tutoriais fora dos cadastros: abrir o caixa e fazer a primeira venda, fechar o caixa, entrada de estoque. O motor
  hoje só conhece lista + formulário de cadastro; o caixa precisa de condições próprias (item lançado, pago, fechado)
  e de decidir se a venda do tutorial é de verdade ou de treino. Combinar com o dono antes.
- "Me mostre como" nos outros passos de Primeiros passos.

## Pendências

- Empório: conta Focus, certificado e CSC no painel da Focus, token de homologação (`docs/NFCE.md`).
- Pix integrado: testar com o Mercado Pago real (Pix de R$ 0,01), ver `docs/PIX.md`.
- Atualização sem UAC (#85): teste em PC real pendente; Render segue com PDV_ATUALIZACAO_PAUSADA=1.
- Antigravity: a nuvem não recebe `nfce_notas` nem `pix_cobrancas` (só locais).
