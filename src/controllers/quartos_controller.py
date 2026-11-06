"""Controle de tempo dos quartos (módulo de operação usar_quartos).

O cliente paga antes, no caixa (venda normal pelo CaixaController); aqui se conta o tempo e os shows da profissional. O tempo é vendido em
blocos (padrão 30 min) e o valor do bloco é só informativo na tela. O início fica gravado no banco e o restante é
calculado pelo relógio: fechar o PDV ou faltar luz não perde a contagem.

Situações de um quarto: 'livre', 'uso', 'alerta' (faltam `quartos_alerta_min` minutos) e 'estourou' (tempo acabou e o
quarto ainda não foi liberado). A campainha do quarto (ESP32 na rede local) é opcional: `quartos_campainhas` mapeia o
número do quarto ao endereço do aparelho.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao

MAX_BLOCOS = 24          # 12 h com o bloco de 30 min
MAX_QUARTOS = 50


def ler_campainhas(texto: str | None) -> dict[int, str]:
    """'1=192.168.0.51; 2=192.168.0.52' -> {1: '192.168.0.51', 2: '192.168.0.52'}. Vazio: sem campainhas."""
    mapa: dict[int, str] = {}
    for parte in (texto or "").replace("\n", ";").replace(",", ";").split(";"):
        parte = parte.strip()
        if not parte:
            continue
        if "=" not in parte:
            raise ErroValidacao(f"Campainha '{parte}': use quarto=endereço (ex.: 1=192.168.0.51).",
                                {"quartos_campainhas": "inválido"})
        num, endereco = (p.strip() for p in parte.split("=", 1))
        if not num.isdigit() or not 1 <= int(num) <= MAX_QUARTOS:
            raise ErroValidacao(f"Campainha '{parte}': o quarto deve ser um número de 1 a {MAX_QUARTOS}.",
                                {"quartos_campainhas": "inválido"})
        if not endereco or any(c in endereco for c in " /?#@"):
            raise ErroValidacao(f"Campainha '{parte}': endereço inválido (ex.: 192.168.0.51).",
                                {"quartos_campainhas": "inválido"})
        mapa[int(num)] = endereco
    return mapa


def fmt_duracao(minutos: int) -> str:
    h, m = divmod(int(minutos), 60)
    if h and m:
        return f"{h}h{m:02d}"
    return f"{h}h" if h else f"{m} min"


def fmt_relogio(segundos: float) -> str:
    s = int(abs(segundos))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dt(iso: str) -> datetime:
    return datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")


class QuartosController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    # ------------------------------------------------------------ configuração
    def ligado(self) -> bool:
        return self.banco.cfg_bool("usar_quartos", False)

    def config(self) -> dict:
        b = self.banco
        show = self._produto_show_configurado()
        if show is not None:
            valor = show["preco_cent"]                  # o preço do show (ex.: código 33) é o valor de cada bloco
        else:
            try:
                valor = fmt.para_centavos(b.cfg("quartos_valor_bloco", "90") or 0)
            except ValueError:
                valor = 0
        return {
            "quartos": max(1, min(MAX_QUARTOS, b.cfg_int("quartos_qtd", 7))),
            "minutos_bloco": max(1, b.cfg_int("quartos_minutos_bloco", 30)),
            "valor_bloco_cent": valor,
            "alerta_min": max(0, b.cfg_int("quartos_alerta_min", 5)),
        }

    def campainhas(self) -> dict[int, str]:
        try:
            return ler_campainhas(self.banco.cfg("quartos_campainhas", ""))
        except ErroValidacao:
            return {}

    def rotulo_blocos(self, blocos: int) -> str:
        """'1h30 — R$ 270,00' para mostrar na escolha do tempo."""
        c = self.config()
        return f"{fmt_duracao(blocos * c['minutos_bloco'])}  —  {fmt.fmt_brl(blocos * c['valor_bloco_cent'])}"

    # ---------------------------------------------------------------- operação
    def _exigir_ligado(self) -> None:
        if not self.ligado():
            raise ErroNegocio("O módulo Quartos está desligado (Configurações > Módulos).")

    def _ativo(self, quarto: int):
        return self.banco.um("SELECT * FROM quartos_uso WHERE quarto = ? AND liberado_em IS NULL", (quarto,))

    def _validar(self, quarto: int, blocos: int) -> None:
        if not 1 <= int(quarto) <= self.config()["quartos"]:
            raise ErroValidacao("Quarto inexistente.", {"quarto": "inválido"})
        if not 1 <= int(blocos) <= MAX_BLOCOS:
            raise ErroValidacao(f"Escolha de 1 a {MAX_BLOCOS} blocos de tempo.", {"blocos": "inválido"})

    @staticmethod
    def _codigo(valor: str | None, nome: str) -> str | None:
        if valor is None or not str(valor).strip():
            return None
        codigo = str(valor).strip()
        if not codigo.isdigit() or not 1 <= len(codigo) <= 6:
            raise ErroValidacao(f"{nome}: use de 1 a 6 dígitos.")
        return codigo

    def nome_profissional(self, codigo: str | None) -> str | None:
        """Consulta o mesmo cadastro de garotas usado nas comissões."""
        if not codigo:
            return None
        registro = self.banco.um(
            "SELECT nome FROM garotas WHERE numero = ?", (int(codigo),))
        return registro["nome"] if registro else None

    def historico(self, quarto: int | None = None, codigo: str | None = None,
                  limite: int = 200) -> list[dict]:
        """Consulta histórica, inclusive utilizações ainda abertas, sem valores financeiros."""
        self._exigir_ligado()
        filtros, params = [], []
        if quarto is not None:
            if not 1 <= int(quarto) <= MAX_QUARTOS:
                raise ErroValidacao("Quarto inválido.")
            filtros.append("quarto = ?")
            params.append(int(quarto))
        if codigo:
            filtros.append("(comanda_cliente = ? OR codigo_profissional = ?)")
            params.extend([self._codigo(codigo, "Código")] * 2)
        where = " WHERE " + " AND ".join(filtros) if filtros else ""
        params.append(max(1, min(int(limite), 1000)))
        registros = [dict(r) for r in self.banco.todos(
            "SELECT id, quarto, inicio, liberado_em, comanda_cliente, codigo_profissional, "
            "operador_id, liberado_por, blocos, minutos_bloco, excedeu_seg "
            "FROM quartos_uso" + where + " ORDER BY inicio DESC, id DESC LIMIT ?", tuple(params))]
        for registro in registros:
            registro["nome_profissional"] = self.nome_profissional(registro["codigo_profissional"])
        return registros

    def iniciar(self, quarto: int, blocos: int, comanda_cliente: str | None = None,
                codigo_profissional: str | None = None) -> int:
        """Começa a contar o tempo do quarto (o cliente já pagou no caixa)."""
        self._exigir_ligado()
        self._validar(quarto, blocos)
        if self._ativo(quarto):
            raise ErroNegocio(f"O quarto {quarto} já está em uso. Libere antes de iniciar de novo.")
        c = self.config()
        comanda_cliente = self._codigo(comanda_cliente, "Comanda do cliente")
        codigo_profissional = self._codigo(codigo_profissional, "Código da profissional")
        if codigo_profissional:
            if not self.nome_profissional(codigo_profissional):
                raise ErroValidacao("Profissional não cadastrada. Cadastre em Comissões primeiro.")
            ocupado = self.banco.um(
                "SELECT quarto FROM quartos_uso WHERE codigo_profissional = ? AND liberado_em IS NULL",
                (codigo_profissional,))
            if ocupado:
                raise ErroNegocio(f"Código {codigo_profissional} já está no quarto {ocupado['quarto']}.")
        with self.banco.transacao():
            uso_id = self.banco.inserir("quartos_uso", {
                "quarto": int(quarto), "inicio": fmt.agora(), "blocos": int(blocos),
                "minutos_bloco": c["minutos_bloco"], "valor_bloco_cent": c["valor_bloco_cent"],
                "operador_id": self.operador_id,
                "comanda_cliente": comanda_cliente, "codigo_profissional": codigo_profissional,
            })
            self._registrar_shows(uso_id, codigo_profissional, 0, int(blocos), c["minutos_bloco"])
        self.banco.log("quarto_iniciado", f"quarto {quarto}: {fmt_duracao(blocos * c['minutos_bloco'])}",
                       self.operador_id)
        return uso_id

    def adicionar_tempo(self, quarto: int, blocos: int) -> None:
        """O cliente pagou mais tempo: soma blocos ao que está contando (conta a partir do fim previsto)."""
        self._exigir_ligado()
        self._validar(quarto, blocos)
        with self.banco.transacao():
            uso = self._ativo(quarto)
            if uso is None:
                raise ErroNegocio(f"O quarto {quarto} está livre.")
            total = uso["blocos"] + int(blocos)
            if total > MAX_BLOCOS:
                raise ErroValidacao(f"O total passaria de {MAX_BLOCOS} blocos.", {"blocos": "inválido"})
            self.banco.executar("UPDATE quartos_uso SET blocos = ? WHERE id = ?", (total, uso["id"]))
            self._registrar_shows(uso["id"], uso["codigo_profissional"], uso["blocos"], total, uso["minutos_bloco"])
        self.banco.log("quarto_mais_tempo", f"quarto {quarto}: +{blocos} bloco(s)", self.operador_id)

    def _registrar_shows(self, uso_id, profissional, antes, depois, minutos_bloco):
        """Cada meia hora contratada gera um show, na mesma transação do tempo."""
        quantidade = depois * minutos_bloco // 30 - antes * minutos_bloco // 30
        if profissional and quantidade:
            return self.banco.inserir("shows_quartos", {
                "uso_id": uso_id, "garota": int(profissional), "blocos_total": depois,
                "quantidade": quantidade, "criado_em": fmt.agora(),
            })
        return None

    def liberar(self, quarto: int) -> dict:
        """Encerra o uso; guarda quanto passou do tempo (0 se saiu dentro do tempo)."""
        self._exigir_ligado()
        uso = self._ativo(quarto)
        if uso is None:
            raise ErroNegocio(f"O quarto {quarto} já está livre.")
        agora = fmt.agora_dt()
        fim = _dt(uso["inicio"]) + timedelta(minutes=uso["blocos"] * uso["minutos_bloco"])
        excedeu = max(0, int((agora - fim).total_seconds()))
        self.banco.executar(
            "UPDATE quartos_uso SET liberado_em = ?, liberado_por = ?, excedeu_seg = ? WHERE id = ?",
            (fmt.agora(), self.operador_id, excedeu, uso["id"]))
        self.banco.log("quarto_liberado", f"quarto {quarto}" + (f", passou {fmt_relogio(excedeu)}" if excedeu else ""),
                       self.operador_id)
        return {"quarto": quarto, "excedeu_seg": excedeu}

    # ------------------------------------------------ quarto pela comanda do cliente
    def _produto_show_configurado(self) -> dict | None:
        """O produto do show escolhido em `quartos_codigo_show` (ex.: 33), se existir e estiver ativo."""
        codigo = (self.banco.cfg("quartos_codigo_show", "") or "").strip()
        if not codigo:
            return None
        from src.controllers.produto_controller import ProdutoController
        p = ProdutoController(self.banco).buscar_codigo(codigo)
        return p if p and p["ativo"] else None

    def produto_quarto(self) -> dict:
        """O produto do show/quarto (um bloco de tempo). Com `quartos_codigo_show` (ex.: 33), é esse produto; senão, o
        QUARTO criado pelo sistema na primeira vez (preço = valor do bloco)."""
        from src.controllers.cadastro_controller import CadastroController
        from src.controllers.produto_controller import ProdutoController
        show = self._produto_show_configurado()
        if show is not None:
            return show
        produtos = ProdutoController(self.banco)
        atual = self.banco.cfg_int("quartos_produto", 0)
        p = produtos.por_id(atual) if atual else None
        if p is not None and p["ativo"]:
            return p
        c = self.config()
        with self.banco.transacao():
            pid = CadastroController(self.banco).salvar("produtos", {
                "codigo": produtos.proximo_codigo(), "nome": f"QUARTO {fmt_duracao(c['minutos_bloco'])}",
                "subgrupo_id": self.banco.valor("SELECT id FROM subgrupos ORDER BY id LIMIT 1"),
                "unidade_id": self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
                or self.banco.valor("SELECT id FROM unidades ORDER BY id LIMIT 1"),
                "preco_cent": fmt.fmt_num(c["valor_bloco_cent"] or 1), "cobrar_servico": "N",
                "mostrar_no_cardapio": "N"})
            self.banco.cfg_set("quartos_produto", pid)
        return produtos.por_id(pid)

    def eh_produto_quarto(self, produto_id) -> bool:
        if not produto_id:
            return False
        show = self._produto_show_configurado()
        if show is not None:
            return show["id"] == produto_id
        return self.banco.cfg_int("quartos_produto", 0) == produto_id

    def garota_cadastrada(self, numero) -> dict | None:
        try:
            numero = int(numero)
        except (TypeError, ValueError):
            return None
        r = self.banco.um("SELECT numero, nome FROM garotas WHERE numero = ?", (numero,))
        return dict(r) if r else None

    def quarto_sugerido(self, excluir: set[int] | None = None) -> int | None:
        """Quarto livre há mais tempo (nunca usado conta como o mais antigo): reveza os quartos e dá tempo de arrumar."""
        excluir = excluir or set()
        ocupados = {r["quarto"] for r in self.banco.todos("SELECT quarto FROM quartos_uso WHERE liberado_em IS NULL")}
        livres = [n for n in range(1, self.config()["quartos"] + 1) if n not in ocupados and n not in excluir]
        if not livres:
            return None
        ultimos = {r["quarto"]: r["fim"] for r in self.banco.todos(
            "SELECT quarto, MAX(liberado_em) AS fim FROM quartos_uso GROUP BY quarto")}
        return min(livres, key=lambda n: (ultimos.get(n) or "", n))

    def _shows_do_uso(self, uso_id: int, blocos_total: int) -> list[int]:
        return [r["id"] for r in self.banco.todos(
            "SELECT id FROM shows_quartos WHERE uso_id = ? AND blocos_total = ?", (uso_id, blocos_total))]

    def registrar_venda(self, venda: dict) -> list[dict]:
        """Chamado no fechamento (pago), dentro da transação da venda: cada garota com quarto lançado vira um início no
        quarto pedido ou sugerido, uma soma no quarto em que ela já está, ou uma espera na fila sem quarto livre."""
        linhas = self.banco.todos(
            """SELECT garota_quarto AS garota, SUM(quantidade) AS blocos, MAX(quarto_pedido) AS quarto
               FROM itens_venda WHERE venda_id = ? AND cancelado = 0 AND garota_quarto IS NOT NULL
               GROUP BY garota_quarto ORDER BY MIN(id)""", (venda["id"],))
        if not linhas:
            return []
        self._exigir_ligado()
        comanda = str(venda.get("posicao") or "") if venda.get("modalidade") == "mesa" else None
        resultados, reservados = [], set()
        for linha in linhas:
            garota, blocos = int(linha["garota"]), int(round(linha["blocos"]))
            if blocos <= 0:
                continue
            nome = (self.garota_cadastrada(garota) or {}).get("nome", "")
            registro = {"venda_id": venda["id"], "garota": garota, "blocos": blocos, "comanda": comanda,
                        "criado_em": fmt.agora()}
            em_uso = self.banco.um("SELECT * FROM quartos_uso WHERE codigo_profissional = ? AND liberado_em IS NULL",
                                   (str(garota),))
            if em_uso:
                self.adicionar_tempo(em_uso["quarto"], blocos)
                total = em_uso["blocos"] + blocos
                registro.update(quarto=em_uso["quarto"], uso_id=em_uso["id"], situacao="somado",
                                show_ids=",".join(map(str, self._shows_do_uso(em_uso["id"], total))))
            else:
                quarto = linha["quarto"]
                if quarto and (self._ativo(quarto) or quarto in reservados):
                    quarto = None                      # o pedido foi ocupado nesse meio tempo: vale o sugerido
                quarto = quarto or self.quarto_sugerido(reservados)
                if quarto is None:
                    registro.update(situacao="aguardando")
                else:
                    uso_id = self.iniciar(quarto, blocos, comanda, str(garota))
                    reservados.add(quarto)
                    registro.update(quarto=quarto, uso_id=uso_id, situacao="iniciado", resolvido_em=fmt.agora(),
                                    show_ids=",".join(map(str, self._shows_do_uso(uso_id, blocos))))
            registro["id"] = self.banco.inserir("quartos_vendas", registro)
            resultados.append({**registro, "nome": nome,
                               "duracao": fmt_duracao(blocos * self.config()["minutos_bloco"])})
        return resultados

    def resultados_da_venda(self, venda_id: int) -> list[dict]:
        """O que o pagamento da venda fez nos quartos (iniciado, somado ou aguardando), para a tela avisar."""
        saida = []
        for r in self.banco.todos("SELECT * FROM quartos_vendas WHERE venda_id = ? AND situacao <> 'cancelado' "
                                  "ORDER BY id", (venda_id,)):
            item = dict(r)
            item["nome"] = (self.garota_cadastrada(item["garota"]) or {}).get("nome", "")
            item["duracao"] = fmt_duracao(item["blocos"] * self.config()["minutos_bloco"])
            saida.append(item)
        return saida

    def fila(self) -> list[dict]:
        saida = []
        for r in self.banco.todos("SELECT * FROM quartos_vendas WHERE situacao = 'aguardando' ORDER BY id"):
            item = dict(r)
            item["nome"] = (self.garota_cadastrada(item["garota"]) or {}).get("nome", "")
            item["duracao"] = fmt_duracao(item["blocos"] * self.config()["minutos_bloco"])
            saida.append(item)
        return saida

    def iniciar_da_fila(self, fila_id: int, quarto: int | None = None) -> dict:
        """Começa o tempo de quem estava esperando quarto (no quarto indicado ou no sugerido)."""
        self._exigir_ligado()
        with self.banco.transacao():
            r = self.banco.um("SELECT * FROM quartos_vendas WHERE id = ? AND situacao = 'aguardando'", (fila_id,))
            if r is None:
                raise ErroNegocio("Essa espera já foi atendida ou cancelada.")
            quarto = quarto or self.quarto_sugerido()
            if quarto is None:
                raise ErroNegocio("Nenhum quarto livre ainda.")
            em_uso = self.banco.um("SELECT * FROM quartos_uso WHERE codigo_profissional = ? AND liberado_em IS NULL",
                                   (str(r["garota"]),))
            if em_uso:
                self.adicionar_tempo(em_uso["quarto"], r["blocos"])
                quarto, uso_id, situacao = em_uso["quarto"], em_uso["id"], "somado"
                shows = self._shows_do_uso(uso_id, em_uso["blocos"] + r["blocos"])
            else:
                uso_id = self.iniciar(quarto, r["blocos"], r["comanda"], str(r["garota"]))
                situacao, shows = "iniciado", self._shows_do_uso(uso_id, r["blocos"])
            self.banco.executar(
                "UPDATE quartos_vendas SET situacao = ?, quarto = ?, uso_id = ?, show_ids = ?, resolvido_em = ? "
                "WHERE id = ?", (situacao, quarto, uso_id, ",".join(map(str, shows)), fmt.agora(), fila_id))
        return {"quarto": quarto, "garota": r["garota"], "situacao": situacao}

    def desfazer_venda(self, venda_id: int) -> None:
        """Cupom cancelado: tira o tempo e os shows que a venda gerou. Recusa se algum show já foi pago no acerto."""
        registros = self.banco.todos(
            "SELECT * FROM quartos_vendas WHERE venda_id = ? AND situacao <> 'cancelado'", (venda_id,))
        for r in registros:
            ids = [int(i) for i in (r["show_ids"] or "").split(",") if i]
            if ids and self.banco.valor(
                    f"SELECT COUNT(*) FROM shows_quartos WHERE acerto_id IS NOT NULL AND id IN ({','.join('?' * len(ids))})",
                    tuple(ids)):
                raise ErroNegocio("O show deste quarto já foi pago no acerto da garota. Cancele o acerto antes.")
        for r in registros:
            ids = [int(i) for i in (r["show_ids"] or "").split(",") if i]
            if ids:
                self.banco.executar(f"DELETE FROM shows_quartos WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
            if r["uso_id"] and r["situacao"] in ("iniciado", "somado"):
                uso = self.banco.um("SELECT * FROM quartos_uso WHERE id = ?", (r["uso_id"],))
                if uso and uso["liberado_em"] is None:
                    restante = uso["blocos"] - r["blocos"]
                    if restante > 0:
                        self.banco.executar("UPDATE quartos_uso SET blocos = ? WHERE id = ?", (restante, uso["id"]))
                    else:
                        self.banco.executar("UPDATE quartos_uso SET liberado_em = ?, liberado_por = ? WHERE id = ?",
                                            (fmt.agora(), self.operador_id, uso["id"]))
            self.banco.executar("UPDATE quartos_vendas SET situacao = 'cancelado', resolvido_em = ? WHERE id = ?",
                                (fmt.agora(), r["id"]))
        if registros:
            self.banco.log("quarto_venda_cancelada", f"venda {venda_id}: {len(registros)} quarto(s) desfeito(s)",
                           self.operador_id)

    # ------------------------------------------------------------------ painel
    def situacao(self) -> list[dict]:
        """Um item por quarto, na ordem, com o estado e o tempo restante (negativo = passou do tempo)."""
        c = self.config()
        agora = fmt.agora_dt()
        ativos = {r["quarto"]: r for r in self.banco.todos(
            "SELECT * FROM quartos_uso WHERE liberado_em IS NULL")}
        lista = []
        for n in range(1, c["quartos"] + 1):
            uso = ativos.get(n)
            if uso is None:
                lista.append({"quarto": n, "estado": "livre", "uso_id": None})
                continue
            inicio = _dt(uso["inicio"])
            minutos = uso["blocos"] * uso["minutos_bloco"]
            fim = inicio + timedelta(minutes=minutos)
            restante = (fim - agora).total_seconds()
            if restante <= 0:
                estado = "estourou"
            elif restante <= c["alerta_min"] * 60:
                estado = "alerta"
            else:
                estado = "uso"
            lista.append({
                "quarto": n, "estado": estado, "uso_id": uso["id"], "inicio": inicio, "fim": fim,
                "blocos": uso["blocos"], "minutos": minutos, "restante_seg": restante,
                "valor_cent": uso["blocos"] * uso["valor_bloco_cent"],
                "comanda_cliente": uso["comanda_cliente"], "codigo_profissional": uso["codigo_profissional"],
            })
        # Quarto em uso acima do número configurado (o dono diminuiu a quantidade): continua visível até ser liberado.
        for n in sorted(q for q in ativos if q > c["quartos"]):
            uso = ativos[n]
            fim = _dt(uso["inicio"]) + timedelta(minutes=uso["blocos"] * uso["minutos_bloco"])
            restante = (fim - agora).total_seconds()
            lista.append({
                "quarto": n, "estado": "estourou" if restante <= 0 else "uso", "uso_id": uso["id"],
                "inicio": _dt(uso["inicio"]), "fim": fim, "blocos": uso["blocos"],
                "minutos": uso["blocos"] * uso["minutos_bloco"], "restante_seg": restante,
                "valor_cent": uso["blocos"] * uso["valor_bloco_cent"],
                "comanda_cliente": uso["comanda_cliente"], "codigo_profissional": uso["codigo_profissional"],
            })
        for item in lista:
            item["nome_profissional"] = self.nome_profissional(item.get("codigo_profissional"))
        return lista

    def resumo_noite(self) -> dict:
        """Usos que começaram na noite atual (o dia vira em `virada_dia_hora`, como no painel)."""
        virada = self.banco.cfg_int("virada_dia_hora", 6)
        ini, fim = fmt.faixa_dia_operacional(fmt.dia_operacional(virada=virada), virada)
        r = self.banco.um(
            "SELECT COUNT(*) AS usos, COALESCE(SUM(blocos * minutos_bloco), 0) AS minutos, "
            "COALESCE(SUM(blocos * valor_bloco_cent), 0) AS valor_cent, "
            "COALESCE(SUM(CASE WHEN excedeu_seg > 0 THEN 1 ELSE 0 END), 0) AS estouros "
            "FROM quartos_uso WHERE inicio >= ? AND inicio < ?", (ini, fim))
        return dict(r)
