---
name: verify
description: Verificar uma mudança do WillPDV antes do commit ou do PR (caixa, nuvem, painel, retaguarda, telas). Use sempre antes de commitar, quando pedirem para "conferir", "testar" ou "verificar", e antes de abrir PR.
---

# Verificar uma mudança do WillPDV

Objetivo: provas de que a mudança funciona, não a impressão de que funciona. Rode, leia a saída e só então commite.

## 1. Rodar o verificador

```
python -m tools.verificar            # fumaça do caixa + testes ligados ao que mudou + node --check nos .js
python -m tools.verificar --telas    # mexeu em src/ui_qt: fotografa as telas em build/telas
```

No Linux sem tela, o verificador já usa `QT_QPA_PLATFORM=offscreen`.

## 2. Exercitar de verdade o que mudou

Teste verde não basta quando a mudança tem tela ou rota:

- **Tela Qt (src/ui_qt):** rode com `--telas` e abra os PNGs das telas mexidas (Read). Confira se cabe em 1280 px,
  se tem botão cortado, coluna truncada, seta do combobox e texto em português.
- **Rota da nuvem (backend/):** chame pela `TestClient` num teste (como `tests/test_retaguarda.py`) com o caminho
  completo: sem sessão (401), sem CSRF (403) e o caminho feliz.
- **Página web (backend/*_web):** `node --check` roda sozinho. Se der, abra no navegador local
  (`uvicorn backend.main:app`) e use a tela.
- **Regra de dinheiro ou estoque:** acrescente um caso a `tests/test_propriedades_dinheiro.py` se a regra vale para
  qualquer venda. Para investigar, rode com `WILLPDV_CASOS=500`.

## 3. Conferir a lista do REVIEW.md

Leia `REVIEW.md` (o da main, não o da branch) e confira só os itens cujo gatilho aparece no diff
(`git diff main...HEAD --stat`).

## 4. Registrar no commit

Cole no fim da mensagem do commit a última linha do verificador, por exemplo
`Verificado: fumaça do caixa; 3 módulos de teste; node --check`. Se nada rodou, escreva `Verificado: nenhum` e diga o
porquê.

## Regras

- Falhou: corrija a causa. Depois de **3 tentativas** sem passar, pare e explique ao dono o que falha e o que você tentou.
- Teste instável: não pule, não ponha `sleep` e não repita até passar. Ache a causa; se não achar, apague o teste e
  explique o porquê no commit.
- Bug que escapou para uma loja: vire um teste e, se dá para ver pelo diff, um item novo no `REVIEW.md`.
