"""Interfaces dos equipamentos do caixa: balança (F2) e gaveta de dinheiro (F11).

A gaveta é aberta pelo pulso ESC/POS da impressora térmica (conector RJ-11 da impressora),
que é o jeito padrão no varejo; veja `impressora_termica.py`. A balança (Toledo/Filizola) depende
de biblioteca serial e do equipamento ligado, que não dá para testar aqui, então ela ainda cai no
modo manual (digitar o peso) com mensagem clara. Para suportar um modelo, implemente `ler_peso`.
"""
from __future__ import annotations

from src.hardware.impressora_termica import ErroImpressao, ImpressoraTermica


class DispositivoIndisponivel(Exception):
    """O equipamento não está configurado ou o driver não está implementado."""


class Balanca:
    def __init__(self, modelo: str = "Nenhuma", porta: str | None = None):
        self.modelo = modelo or "Nenhuma"
        self.porta = porta

    @property
    def configurada(self) -> bool:
        return self.modelo != "Nenhuma" and bool(self.porta)

    def ler_peso(self) -> float:
        """Peso em kg. Comunica via Serial com Toledo ou Filizola."""
        if not self.configurada:
            raise DispositivoIndisponivel("Balança não configurada ou sem porta COM definida.")
            
        try:
            import serial
        except ImportError:
            raise DispositivoIndisponivel("A balança precisa do pyserial instalado (pip install pyserial).") from None
        import time

        try:
            # Configuração padrão de porta serial para balanças BR (9600 ou 4800, 8, N, 1)
            # Para Toledo Prix 3 e Filizola CS
            with serial.Serial(self.porta, 9600, timeout=1) as ser:
                ser.flushInput()
                
                if 'filizola' in self.modelo.lower():
                    # Filizola responde ao ENQ (0x05)
                    ser.write(b'\x05')
                    time.sleep(0.1)
                    
                # Lê os próximos 20 bytes (normalmente manda pacotes de 6 a 10 bytes)
                dado = ser.read(20)
                
                if not dado:
                    raise DispositivoIndisponivel("Balança não respondeu (timeout). Verifique o cabo.")
                    
                # Protocolo Toledo (STX + 5 ou 6 bytes + ETX) ou Filizola
                # Exemplo: b'\x0201234\x03'
                import re
                match = re.search(rb'\x02(\d{5,6})\x03', dado)
                if match:
                    peso_str = match.group(1).decode('ascii')
                    # Assume 3 casas decimais (gramas -> kg)
                    return int(peso_str) / 1000.0
                else:
                    raise DispositivoIndisponivel(f"Dados não reconhecidos no protocolo: {dado}")
                    
        except serial.SerialException as e:
            raise DispositivoIndisponivel(f"Erro na porta serial {self.porta}: {e}")


class Gaveta:
    """Gaveta de dinheiro. Abre pelo pulso da impressora térmica quando a impressora está
    configurada com 'gaveta ligada à impressora'; senão informa que deve ser aberta com a chave."""

    def __init__(self, instalada: bool = False, impressora: ImpressoraTermica | None = None):
        self.instalada = instalada
        self.impressora = impressora

    @property
    def automatica(self) -> bool:
        return bool(self.impressora and self.impressora.configurada and self.impressora.tem_gaveta)

    def abrir(self) -> None:
        if not self.instalada and not self.automatica:
            raise DispositivoIndisponivel("Nenhuma gaveta configurada (Configurações > Máquinas).")
        if not self.automatica:
            raise DispositivoIndisponivel(
                "A gaveta não está ligada à impressora térmica. Marque 'Gaveta ligada à impressora' em "
                "Configurações > Máquinas, ou abra com a chave.")
        try:
            self.impressora.abrir_gaveta()
        except ErroImpressao as e:
            raise DispositivoIndisponivel(str(e)) from e
