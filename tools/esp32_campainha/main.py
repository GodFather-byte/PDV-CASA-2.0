# ==========================================================
# Campainha do Quarto — ESP32 (MicroPython)
# Grave este arquivo no ESP32 com o nome main.py (via Thonny)
# Mude IP e PINOS para cada quarto.
#
# Comandos que o PDV manda:
#   /ping    -> responde "ok" (PDV sabe que está online)
#   /alerta  -> 1 toque curto + LED piscando devagar (faltam 5 min)
#   /tocar   -> campainha + LED piscando rápido (tempo acabou)
#   /parar   -> desliga tudo
# ==========================================================
import network
import socket
import time
from machine import Pin, Timer, WDT

# ---------------- CONFIGURAÇÃO ----------------
SSID = "NOME_DO_WIFI"
SENHA = "SENHA_DO_WIFI"

IP = "192.168.0.51"          # Quarto 1 = .51, Quarto 2 = .52 ...
MASCARA = "255.255.255.0"
GATEWAY = "192.168.0.1"      # IP do roteador
DNS = "8.8.8.8"

PINO_CAMPAINHA = 26          # buzzer ou módulo relé
PINO_LED = 2                 # 2 = LED azul da própria placa
RELE_ATIVO_EM_BAIXO = False  # mude para True se o relé ligar com sinal baixo

TOQUES = 3                   # quantos "trim" quando o tempo acaba
TOQUES_AVISO = 1             # quantos "trim" no aviso de 5 minutos (0 = só o LED)
DURACAO_TOQUE = 0.7          # segundos
PAUSA_TOQUE = 0.4
# ----------------------------------------------

campainha = Pin(PINO_CAMPAINHA, Pin.OUT)
led = Pin(PINO_LED, Pin.OUT, value=0)
pisca = Timer(0)
wdt = WDT(timeout=60000)     # reinicia sozinho se travar


def campainha_on(ligar):
    campainha.value((not ligar) if RELE_ATIVO_EM_BAIXO else ligar)


campainha_on(False)


def piscar(ativo, periodo=500):
    pisca.deinit()
    if ativo:
        pisca.init(period=periodo, mode=Timer.PERIODIC,
                   callback=lambda t: led.value(not led.value()))
    else:
        led.value(0)


def tocar(vezes=TOQUES):
    for _ in range(vezes):
        campainha_on(True)
        time.sleep(DURACAO_TOQUE)
        campainha_on(False)
        time.sleep(PAUSA_TOQUE)


def conectar():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.ifconfig((IP, MASCARA, GATEWAY, DNS))
    if not wlan.isconnected():
        wlan.connect(SSID, SENHA)
        for _ in range(30):
            if wlan.isconnected():
                break
            led.value(not led.value())   # piscando = conectando
            time.sleep(1)
            wdt.feed()
    led.value(0)
    print("Wi-Fi:", wlan.isconnected(), wlan.ifconfig())
    return wlan


def responder(cl, texto):
    cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n" + texto)
    cl.close()


def main():
    wlan = conectar()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 80))
    s.listen(2)
    s.settimeout(5)

    while True:
        wdt.feed()
        if not wlan.isconnected():
            wlan = conectar()
        try:
            cl, _ = s.accept()
        except OSError:
            continue
        try:
            cl.settimeout(2)
            req = cl.recv(512).decode()
            partes = req.split(" ")
            caminho = partes[1] if len(partes) > 1 else "/"

            if caminho == "/ping":
                responder(cl, "ok")
            elif caminho == "/alerta":
                piscar(True, 700)
                responder(cl, "alerta")    # responde antes para o PDV não esperar
                tocar(TOQUES_AVISO)
            elif caminho == "/tocar":
                piscar(True, 200)
                responder(cl, "tocando")   # responde antes para o PDV não esperar
                tocar()
            elif caminho == "/parar":
                piscar(False)
                campainha_on(False)
                responder(cl, "parado")
            else:
                responder(cl, "comando desconhecido")
        except Exception as e:
            print("erro:", e)
            try:
                cl.close()
            except Exception:
                pass


main()
