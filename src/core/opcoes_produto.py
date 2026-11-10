"""Contrato público das opções: centavos inteiros, limites por grupo e seleção sem preço do cliente."""
from uuid import UUID


def catalogo(grupos):
    if not isinstance(grupos, list) or len(grupos) > 12:
        raise ValueError("Cadastre até 12 grupos de opções.")
    saida, usados = [], set()
    for g in grupos:
        if not isinstance(g, dict):
            raise ValueError("Grupo inválido.")
        uid = str(UUID(str(g["id"])))
        nome = str(g.get("nome") or "").strip()
        minimo, maximo = g.get("minimo", 0), g.get("maximo", 1)
        if uid in usados or not nome or len(nome) > 60:
            raise ValueError("Grupo repetido ou nome inválido.")
        usados.add(uid)
        if type(minimo) is not int or type(maximo) is not int or not 0 <= minimo <= maximo <= 20:
            raise ValueError("Limites do grupo inválidos.")
        opcoes = g.get("opcoes")
        if not isinstance(opcoes, list) or not 1 <= len(opcoes) <= 20 or minimo > len(opcoes):
            raise ValueError("Cadastre de 1 a 20 opções por grupo, respeitando o mínimo.")
        limpas = []
        for o in opcoes:
            if not isinstance(o, dict):
                raise ValueError("Opção inválida.")
            oid = str(UUID(str(o["id"])))
            texto, preco = str(o.get("nome") or "").strip(), o.get("preco_cent")
            if oid in usados or not texto or len(texto) > 60:
                raise ValueError("Opção repetida ou nome inválido.")
            if type(preco) is not int or not 0 <= preco <= 10_000_000:
                raise ValueError("Preço da opção inválido; use centavos inteiros não negativos.")
            usados.add(oid)
            limpas.append({"id": oid, "nome": texto, "preco_cent": preco})
        saida.append({"id": uid, "nome": nome, "minimo": minimo, "maximo": maximo, "opcoes": limpas})
    return saida


def selecionar(grupos, ids=None):
    grupos = catalogo(grupos)
    ids = [] if ids is None else ids
    if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
        raise ValueError("Seleção de opções inválida.")
    if len(set(ids)) != len(ids):
        raise ValueError("Uma opção não pode ser selecionada duas vezes.")
    escolhidos, conhecidos = [], set()
    for g in grupos:
        linhas = [o for o in g["opcoes"] if o["id"] in ids]
        if not g["minimo"] <= len(linhas) <= g["maximo"]:
            raise ValueError(f"{g['nome']}: escolha de {g['minimo']} a {g['maximo']} opção(ões).")
        for o in g["opcoes"]:
            conhecidos.add(o["id"])
        escolhidos.extend({"id": o["id"], "grupo": g["nome"], "nome": o["nome"],
                           "preco_cent": o["preco_cent"]} for o in linhas)
    if set(ids) - conhecidos:
        raise ValueError("Uma opção saiu do cadastro. Atualize o produto e escolha novamente.")
    return escolhidos
