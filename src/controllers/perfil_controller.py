"""Perfil do estabelecimento: o "modo de operação" do PDV (boate, bar, restaurante, churrascaria ou comércio pequeno).

É um atalho de configuração: liga e desliga de uma vez os módulos e as regras de sim/não que definem o tipo de negócio, e
nada além disso. O que o dono digitou (códigos, preços, percentuais, número de mesas e comandas) não muda. Depois de
aplicado, cada chave continua ajustável em Configurações; o perfil gravado é só a referência do que foi escolhido."""
from __future__ import annotations

from src.controllers.config_controller import CAMPOS_CONFIG, ConfigController
from src.core.erros import ErroNegocio
from src.database.sementes import CONFIG_PADRAO

# O que o perfil controla, na ordem em que aparece na confirmação, com o nome curto de cada item.
ITENS = {
    "usar_mesas": "Mesas e comandas no caixa",
    "usar_garotas": "Garotas (comissão e shows)", "usar_portaria": "Portaria (ticket de saída)",
    "usar_cozinha_bar": "Cozinha/Bar (pedido por setor)", "usar_rodizio": "Rodízio por pessoa", "usar_delivery": "Delivery",
    "usar_caderneta": "Caderneta (fiado)", "posicao_padrao": "Número digitado no caixa é",
    "cobra_servico_mesa": "Serviço nas mesas", "cobra_servico_comanda": "Serviço nas comandas",
    "pergunta_pessoas": "Perguntar o nº de pessoas ao abrir a mesa", "usar_desconto": "Desconto no fechamento da conta",
    "agrupar_itens_balcao": "Agrupar produtos iguais no balcão",
}

_BOATE = {"usar_mesas": "S", "usar_garotas": "S", "usar_portaria": "S", "usar_cozinha_bar": "N", "usar_rodizio": "N",
          "usar_delivery": "N", "usar_caderneta": "N", "posicao_padrao": "comanda", "cobra_servico_mesa": "S",
          "cobra_servico_comanda": "S", "pergunta_pessoas": "N", "usar_desconto": "N", "agrupar_itens_balcao": "N"}
_SEM_BOATE = {**_BOATE, "usar_garotas": "N", "usar_portaria": "N", "usar_desconto": "S"}
_RESTAURANTE = {**_SEM_BOATE, "usar_cozinha_bar": "S", "usar_delivery": "S", "posicao_padrao": "mesa", "pergunta_pessoas": "S"}

# chave -> (nome, o que ele liga, valores). A boate é o padrão de fábrica: os mesmos valores de CONFIG_PADRAO.
PERFIS = {
    "boate": ("Boate / casa noturna", "comanda, comissão das garotas e shows, ticket de saída para a portaria e sem "
              "desconto. É como o sistema sempre funcionou", _BOATE),
    "bar": ("Bar", "comanda e mesa com serviço, pedido por setor (cozinha/bar) e desconto liberado",
            {**_SEM_BOATE, "usar_cozinha_bar": "S"}),
    "restaurante": ("Restaurante", "mesa com serviço e nº de pessoas, pedido por setor na cozinha, delivery e desconto "
                    "liberado", _RESTAURANTE),
    "churrascaria": ("Churrascaria / rodízio", "como o restaurante, com o rodízio por pessoa e sem delivery",
                     {**_RESTAURANTE, "usar_rodizio": "S", "usar_delivery": "N"}),
    "comercio": ("Comércio pequeno", "venda só no balcão, sem serviço, caderneta (fiado) e desconto liberado: mercearia, "
                 "padaria, loja, lanchonete",
                 {**_SEM_BOATE, "usar_mesas": "N", "usar_caderneta": "S", "cobra_servico_mesa": "N",
                  "cobra_servico_comanda": "N"}),
    "adega": ("Adega / depósito de bebidas", "venda só no balcão pelo leitor de código de barras, fardo e caixa fechada, "
              "delivery, caderneta (fiado) e desconto liberado",
              {**_SEM_BOATE, "usar_mesas": "N", "usar_delivery": "S", "usar_caderneta": "S", "cobra_servico_mesa": "N",
               "cobra_servico_comanda": "N", "agrupar_itens_balcao": "S"}),
}
PADRAO = "boate"

# Categorias (grupo: subgrupos) que o perfil cria se ainda não existirem: nunca apaga nem renomeia as da casa.
CATEGORIAS = {
    "adega": {"BEBIDAS": ["CERVEJAS", "DESTILADOS", "VINHOS E ESPUMANTES", "REFRIGERANTES", "ÁGUAS E SUCOS", "ENERGÉTICOS"],
              "CONVENIÊNCIA": ["GELO E CARVÃO", "TABACARIA", "PETISCOS", "DESCARTÁVEIS"]},
}
_OPCOES = {c[0]: dict(c[4]) for c in CAMPOS_CONFIG if c[0] in ITENS and len(c) > 4}


class PerfilController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    def atual(self) -> str:
        """O perfil escolhido por último (a boate, para quem nunca escolheu)."""
        perfil = self.banco.cfg("perfil_operacao", PADRAO)
        return perfil if perfil in PERFIS else PADRAO

    def ajustado(self) -> bool:
        """Alguma chave do perfil atual foi mudada à mão depois, em Configurações."""
        return bool(self.mudancas(self.atual()))

    def mudancas(self, perfil: str) -> list[dict]:
        """O que aplicar `perfil` mudaria agora: [{chave, item, de, para, valor}], com `de` e `para` em palavras."""
        valores = self._valores(perfil)
        saida = []
        for chave, item in ITENS.items():
            atual, novo = self._valor_atual(chave), valores[chave]
            if atual != novo:
                saida.append({"chave": chave, "item": item, "de": self._texto(chave, atual), "para": self._texto(chave, novo),
                              "valor": novo})
        return saida

    def aplicar(self, perfil: str) -> list[dict]:
        """Grava o perfil e as chaves dele que estão diferentes, pelas mesmas validações das Configurações (ligar a comissão ou
        a portaria confere se o código dela não é de um produto). Tudo ou nada. Devolve o que mudou."""
        mudancas = self.mudancas(perfil)
        with self.banco.transacao():
            if mudancas:
                ConfigController(self.banco).salvar_config({m["chave"]: m["valor"] for m in mudancas})
            for grupo, subgrupos in self.categorias_faltando(perfil).items():
                self.banco.executar("INSERT OR IGNORE INTO grupos(nome) VALUES (?)", (grupo,))
                grupo_id = self.banco.valor("SELECT id FROM grupos WHERE nome = ?", (grupo,))
                for nome in subgrupos:
                    self.banco.executar("INSERT OR IGNORE INTO subgrupos(nome, grupo_id) VALUES (?, ?)", (nome, grupo_id))
            self.banco.cfg_set("perfil_operacao", perfil)
            self.banco.log("perfil_operacao", f"{PERFIS[perfil][0]}: "
                           + (", ".join(f"{m['item']} {m['para']}" for m in mudancas) or "nada mudou"), self.operador_id)
        return mudancas

    def categorias_faltando(self, perfil: str) -> dict[str, list[str]]:
        """As categorias do perfil (grupo: subgrupos) que a casa ainda não tem."""
        self._valores(perfil)
        faltando = {}
        for grupo, subgrupos in CATEGORIAS.get(perfil, {}).items():
            existentes = {r[0] for r in self.banco.todos(
                "SELECT s.nome FROM subgrupos s JOIN grupos g ON g.id = s.grupo_id WHERE g.nome = ?", (grupo,))}
            novos = [s for s in subgrupos if s not in existentes]
            if novos:
                faltando[grupo] = novos
        return faltando

    @staticmethod
    def _valores(perfil: str) -> dict:
        if perfil not in PERFIS:
            raise ErroNegocio(f"Perfil desconhecido: {perfil}.")
        return PERFIS[perfil][2]

    def _valor_atual(self, chave: str) -> str:
        padrao = CONFIG_PADRAO[chave]
        if chave in _OPCOES:
            return self.banco.cfg(chave, padrao)
        return "S" if self.banco.cfg_bool(chave, padrao == "S") else "N"

    @staticmethod
    def _texto(chave: str, valor: str) -> str:
        if chave in _OPCOES:
            return _OPCOES[chave].get(valor, valor).split(" (")[0]
        if chave.startswith("usar_"):
            return "Ligado" if valor == "S" else "Desligado"
        return "Sim" if valor == "S" else "Não"
