"""
Cenário SIMULADO (fictício) do compressor C-101 para a demonstração da IHM.

- Gera séries temporais determinísticas (semente fixa -> resultados reproduzíveis).
- Executa, sobre as MESMAS amostras:
    Cenário A: anunciador ingênuo, sem racionalização (cada cruzamento do limite
               vira uma notificação; sem atraso, banda morta, correlação nem
               verificação de qualidade).
    Cenário B: o motor AlarmProcessor de automacao.py.
- Executar diretamente imprime o comparativo:  python cenario_compressor.py

Nada aqui representa dados de planta real.
"""
import logging
import random
from typing import Dict, List, Any

from automacao import AlarmProcessor, AlarmPriority, SensorSignal

T_INICIO = 1_700_000_000.0   # relógio da simulação (epoch arbitrário)
DT = 0.5                     # período de amostragem (s)
DURACAO = 150.0              # duração do cenário (s)
SEMENTE = 42

# Configuração das tags (limite, faixa, prioridade, textos para o operador)
TAGS: List[Dict[str, Any]] = [
    dict(sensor_id="PT_101", tag="TRIP_MAIN_COMPRESSOR_C101", limit=85.0, span=100.0,
         priority=AlarmPriority.CRITICAL, direction="HI", unit="bar", equipment="Compressor C-101",
         description="Pressão de descarga muito alta - risco de trip do compressor C-101",
         recommended_action="Abrir a válvula de reciclo (anti-surge) FV-101 e reduzir a carga; se passar de 95 bar, aplicar o procedimento de parada de emergência PE-C101."),
    dict(sensor_id="FT_102", tag="LOW_FLOW_STAGE1", limit=40.0, span=100.0,
         priority=AlarmPriority.HIGH, direction="LO", unit="m³/h", equipment="Compressor C-101 - 1º estágio",
         description="Vazão de sucção do 1º estágio baixa",
         recommended_action="Consequência esperada do trip: acompanhar; agir na causa-raiz (C-101)."),
    dict(sensor_id="PT_103", tag="PRESSURE_DROP_HEADER", limit=30.0, span=100.0,
         priority=AlarmPriority.HIGH, direction="LO", unit="bar", equipment="Coletor de gás",
         description="Pressão do coletor de gás baixa",
         recommended_action="Consequência esperada do trip: verificar consumidores do coletor após estabilizar o C-101."),
    dict(sensor_id="TT_104", tag="TEMP_RISE_INTERCOOLER", limit=60.0, span=150.0,
         priority=AlarmPriority.MEDIUM, direction="HI", unit="°C", equipment="Resfriador intermediário E-102",
         description="Temperatura de saída do resfriador intermediário alta",
         recommended_action="Consequência esperada do trip: confirmar água de resfriamento em operação."),
    dict(sensor_id="LT_201", tag="HIGH_LEVEL_SEAL_OIL", limit=75.0, span=100.0,
         priority=AlarmPriority.MEDIUM, direction="HI", unit="%", equipment="Vaso de óleo de selagem V-201",
         description="Nível do vaso de óleo de selagem alto",
         recommended_action="Verificar dreno do V-201 e válvula LV-201."),
    dict(sensor_id="TT_105", tag="HIGH_TEMP_BEARING_C101", limit=95.0, span=150.0,
         priority=AlarmPriority.HIGH, direction="HI", unit="°C", equipment="Mancal do C-101",
         description="Temperatura do mancal do C-101 alta",
         recommended_action="Verificar óleo de lubrificação; preparar parada se a temperatura continuar subindo."),
]

EVENTOS_ROTEIRO = [
    (0, "Operação normal. Nível do vaso V-201 oscila em torno do limite (ruído)."),
    (30, "Pressão de descarga do C-101 começa a subir."),
    (62, "Pressão ultrapassa 85 bar de forma sustentada."),
    (75, "Trip do compressor: vazão, pressão do coletor e temperatura do resfriador se desviam."),
    (95, "Sensor de temperatura do mancal (TT-105) perde qualidade de sinal."),
    (115, "Sinal do TT-105 é restabelecido; pressão de descarga em queda após o trip."),
]


def gerar_amostras(semente: int = SEMENTE) -> List[List[SensorSignal]]:
    """Retorna uma lista de 'passos'; cada passo contém uma amostra por sensor."""
    rnd = random.Random(semente)
    passos = []
    n = int(DURACAO / DT)
    for i in range(n + 1):
        s = i * DT
        ts = T_INICIO + s
        ruido = lambda a: rnd.uniform(-a, a)
        trip = s >= 75.0

        # Pressão de descarga: 78 bar, sobe a partir de 30 s, cruza 85 com ruído, trip em 75 s
        if s < 30:
            pt101 = 78 + ruido(1.0)
        elif s < 75:
            pt101 = 78 + (s - 30) * 0.33 + ruido(1.6)
        else:
            pt101 = max(20.0, 92 - (s - 75) * 0.6) + ruido(0.8)

        ft102 = (62 + ruido(2)) if not trip else max(12.0, 62 - (s - 75) * 6) + ruido(1.5)
        pt103 = (48 + ruido(1.5)) if not trip else max(15.0, 48 - (s - 75) * 2.5) + ruido(1.0)
        tt104 = (45 + ruido(1.0)) if not trip else min(78.0, 45 + (s - 75) * 1.8) + ruido(0.8)
        # Nível com oscilação rápida em torno de 75 % (alarme incômodo / chattering)
        lt201 = 75.0 + 0.9 * (1 if (i % 3) == 0 else -1) + ruido(0.3)
        tt105 = 72 + ruido(1.0)
        q105 = not (95.0 <= s < 115.0)
        if not q105:
            tt105 = 0.0  # leitura típica de instrumento em falha

        passos.append([
            SensorSignal("PT_101", round(pt101, 2), ts),
            SensorSignal("FT_102", round(ft102, 2), ts),
            SensorSignal("PT_103", round(pt103, 2), ts),
            SensorSignal("TT_104", round(tt104, 2), ts),
            SensorSignal("LT_201", round(lt201, 2), ts),
            SensorSignal("TT_105", round(tt105, 2), ts, quality_good=q105),
        ])
    return passos


class AnunciadorSemRacionalizacao:
    """
    Cenário A: comportamento típico de um sistema mal configurado.
    Cada transição normal -> violação gera nova linha, sem atraso, sem banda morta,
    sem correlação, sem prioridade diferenciada e sem checar qualidade do sinal.
    """
    def __init__(self, tags: List[Dict[str, Any]]):
        self.cfg = {t["sensor_id"]: t for t in tags}
        self.em_violacao: Dict[str, bool] = {}
        self.notificacoes: List[Dict[str, Any]] = []

    def processar(self, sig: SensorSignal) -> None:
        c = self.cfg.get(sig.sensor_id)
        if not c:
            return
        viol = sig.value > c["limit"] if c["direction"] == "HI" else sig.value < c["limit"]
        if viol and not self.em_violacao.get(sig.sensor_id, False):
            self.notificacoes.append({
                "timestamp": sig.timestamp,
                "texto": f"ALARME {sig.sensor_id} {c['direction']} {sig.value:.1f}",
                "tag": c["tag"],
            })
        self.em_violacao[sig.sensor_id] = viol


def novo_motor() -> AlarmProcessor:
    p = AlarmProcessor()
    for t in TAGS:
        p.configure_alarm_tag(**t)
    return p


def executar_completo(semente: int = SEMENTE) -> Dict[str, Any]:
    """Roda o cenário inteiro sem interação do operador e devolve as contagens."""
    passos = gerar_amostras(semente)
    a = AnunciadorSemRacionalizacao(TAGS)
    b = novo_motor()
    for passo in passos:
        for sig in passo:
            a.processar(sig)
            b.process_telemetry(sig)
    por_tag_a: Dict[str, int] = {}
    for n in a.notificacoes:
        por_tag_a[n["tag"]] = por_tag_a.get(n["tag"], 0) + 1
    return {
        "amostras_por_sensor": len(passos),
        "duracao_s": DURACAO,
        "A_total_notificacoes": len(a.notificacoes),
        "A_por_tag": por_tag_a,
        "B_contadores": dict(b.counters),
        "B_anunciados_por_tag": sorted({e["tag"] for e in b.event_log if e["evento"] == "ANUNCIADO"}),
        "B_prioridades_finais": {t: al.priority.name for t, al in b.last_alarm_by_tag.items()},
    }


if __name__ == "__main__":
    logging.getLogger("IndustrialAlarmEngine").setLevel(logging.CRITICAL)
    r = executar_completo()
    print("=" * 66)
    print("RESULTADO DA SIMULAÇÃO (cenário fictício, semente", SEMENTE, ")")
    print("=" * 66)
    print(f"Duração simulada: {r['duracao_s']:.0f} s | amostras por sensor: {r['amostras_por_sensor']}")
    print(f"\nCenário A - sem racionalização: {r['A_total_notificacoes']} notificações")
    for tag, n in sorted(r["A_por_tag"].items(), key=lambda x: -x[1]):
        print(f"   {n:4d}  {tag}")
    c = r["B_contadores"]
    print(f"\nCenário B - com gestão de alarmes: {c['anunciados']} anunciações")
    for tag in r["B_anunciados_por_tag"]:
        print(f"   prioridade final {r['B_prioridades_finais'][tag]:9s} {tag}")
    print(f"   sintomas rebaixados por correlação: {c['rebaixados_correlacao']}")
    print(f"   repetições agrupadas na mesma linha: {c['repeticoes_agrupadas']}")
    print(f"   alarmes de instrumento (qualidade ruim): {c['qualidade_ruim']}")
    print("\nObs.: contagens de uma simulação didática; não são medições de planta real.")
