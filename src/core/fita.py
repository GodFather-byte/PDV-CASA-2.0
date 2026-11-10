"""Fita econômica: o mesmo documento em menos papel.

Não muda nenhum valor nem remove informação: só tira o que é enfeite (molduras de três linhas, linhas em branco,
separadores repetidos). O espaço para assinar e as linhas em destaque continuam como estão.
"""
from __future__ import annotations


def _so_de(linha: str, caractere: str) -> bool:
    cru = linha.strip()
    return len(cru) >= 8 and set(cru) == {caractere}


def _faixa(linha: str) -> bool:
    """Título de seção entre traços: '------ PAGAMENTO ------'."""
    cru = linha.strip()
    return cru.startswith("--") and cru.endswith("--") and any(c.isalnum() for c in cru)


def compactar(texto: str, largura: int = 40, destaques=()) -> str:
    """Devolve o documento compacto para a fita de `largura` colunas.

    `destaques` são os prefixos das linhas que a impressora sai em letra grande (TOTAL, SOBROU...): elas ficam
    numa linha só delas, sem moldura, para o destaque continuar valendo.
    """
    linhas = texto.split("\n")
    # 1) Moldura de três linhas (==== / TÍTULO / ====) vira uma linha.
    sem_moldura: list[str] = []
    i = 0
    while i < len(linhas):
        if (i + 2 < len(linhas) and _so_de(linhas[i], "=") and _so_de(linhas[i + 2], "=")
                and linhas[i + 1].strip() and not _so_de(linhas[i + 1], "=")):
            miolo = linhas[i + 1].strip()
            if any(miolo.startswith(p) for p in destaques):
                sem_moldura.append(linhas[i + 1])
            elif len(miolo) + 6 <= largura:
                sem_moldura.append(f" {miolo} ".center(largura, "="))
            else:
                sem_moldura += ["=" * largura, linhas[i + 1]]
            i += 3
        else:
            sem_moldura.append(linhas[i])
            i += 1
    # 2) Linha em branco só fica antes de linha de assinatura (é o espaço para assinar).
    sem_branco: list[str] = []
    for i, linha in enumerate(sem_moldura):
        if linha.strip():
            sem_branco.append(linha)
            continue
        seguinte = next((l for l in sem_moldura[i + 1:] if l.strip()), "")
        if _so_de(seguinte, "_"):
            sem_branco.append(linha)
    # 3) Separador colado em outro separador ou em título de seção é repetição.
    saida: list[str] = []
    for i, linha in enumerate(sem_branco):
        seguinte = sem_branco[i + 1] if i + 1 < len(sem_branco) else ""
        if _so_de(linha, "-") and (_so_de(seguinte, "-") or _so_de(seguinte, "=") or _faixa(seguinte) or not seguinte):
            continue
        if _so_de(linha, "-") and saida and (_so_de(saida[-1], "=") or _faixa(saida[-1])):
            continue
        saida.append(linha)
    return "\n".join(saida)
