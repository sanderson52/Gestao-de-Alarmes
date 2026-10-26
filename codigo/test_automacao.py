"""
Testes automatizados do motor de alarmes (unittest, biblioteca padrão).
Executar:  python -m unittest -v test_automacao.py

Cada teste marcado com [Pn] reproduz um defeito encontrado na auditoria da P2:
o teste FALHA com a versão da P1 e PASSA com a versão corrigida.
"""
import logging
import unittest

from automacao import (AlarmProcessor, AlarmPriority, AlarmState, SensorSignal,
                       PlantOperatingState, AntiChatteringFilter, DeduplicationFilter,
                       LatencyMonitor, run_comprehensive_industrial_test)

logging.getLogger("IndustrialAlarmEngine").setLevel(logging.CRITICAL)

T0 = 1_700_000_000.0


def novo_processador():
    p = AlarmProcessor()
    p.configure_alarm_tag("PT_101", "TRIP_MAIN_COMPRESSOR_C101", 85.0, 100.0,
                          AlarmPriority.CRITICAL, "Pressão de descarga crítica", "HI")
    p.configure_alarm_tag("FT_102", "LOW_FLOW_STAGE1", 40.0, 100.0,
                          AlarmPriority.HIGH, "Baixa vazão de sucção", "LO")
    p.configure_alarm_tag("LT_201", "HIGH_LEVEL_SEAL_OIL", 75.0, 100.0,
                          AlarmPriority.MEDIUM, "Nível alto óleo de selagem", "HI")
    return p


def sustentar(p, sensor, valor, t, passos=2, dt=1.6):
    """Envia amostras suficientes para vencer o on-delay (1,5 s). Retorna (último resultado, t)."""
    res = None
    for _ in range(passos):
        res_i = p.process_telemetry(SensorSignal(sensor, valor, t))
        res = res_i or res
        t += dt
    return res, t


class TestFiltros(unittest.TestCase):
    def test_on_delay_suprime_ruido(self):
        f = AntiChatteringFilter(deadband_percent=0.02, on_delay_sec=1.5)
        t = T0
        for v in [75.2, 74.8, 75.4, 74.9, 75.5]:
            t += 0.2
            self.assertFalse(f.evaluate("LT", v, 75.0, 100.0, t, "HI"))

    def test_histerese_hi(self):
        f = AntiChatteringFilter(deadband_percent=0.02, on_delay_sec=1.5)
        f.evaluate("PT", 90, 85, 100, T0, "HI")
        self.assertTrue(f.evaluate("PT", 90, 85, 100, T0 + 1.6, "HI"))
        self.assertTrue(f.evaluate("PT", 84.0, 85, 100, T0 + 2.0, "HI"))   # dentro da banda morta
        self.assertFalse(f.evaluate("PT", 82.9, 85, 100, T0 + 2.5, "HI"))  # abaixo de 85-2

    def test_histerese_lo(self):
        f = AntiChatteringFilter(deadband_percent=0.02, on_delay_sec=1.5)
        f.evaluate("FT", 30, 40, 100, T0, "LO")
        self.assertTrue(f.evaluate("FT", 30, 40, 100, T0 + 1.6, "LO"))
        self.assertTrue(f.evaluate("FT", 41.0, 40, 100, T0 + 2.0, "LO"))
        self.assertFalse(f.evaluate("FT", 42.5, 40, 100, T0 + 2.5, "LO"))

    def test_direcao_invalida(self):
        with self.assertRaises(ValueError):
            AntiChatteringFilter().evaluate("X", 1, 1, 1, T0, "MEIO")

    def test_P6_dedup_primeiro_alarme_com_relogio_em_zero(self):
        """[P6] Na P1, timestamp < janela era suprimido porque o padrão era 0.0."""
        d = DeduplicationFilter(suppression_window_sec=8.0)
        self.assertFalse(d.should_suppress("TAG", 3.2))
        self.assertTrue(d.should_suppress("TAG", 5.0))
        self.assertFalse(d.should_suppress("TAG", 12.0))


class TestCicloDeVida(unittest.TestCase):
    def test_P5_alarme_normaliza_apos_reconhecimento(self):
        """[P5] Na P1 o alarme nunca saía da lista de ativos."""
        p = novo_processador()
        alarm, t = sustentar(p, "PT_101", 92.0, T0)
        self.assertIsNotNone(alarm)
        self.assertTrue(p.acknowledge("TRIP_MAIN_COMPRESSOR_C101", "op1", t))
        p.process_telemetry(SensorSignal("PT_101", 30.0, t + 1))
        self.assertNotIn("TRIP_MAIN_COMPRESSOR_C101", p.active_alarms)

    def test_normalizado_sem_reconhecimento_permanece_visivel(self):
        p = novo_processador()
        _, t = sustentar(p, "PT_101", 92.0, T0)
        p.process_telemetry(SensorSignal("PT_101", 30.0, t))
        a = p.active_alarms["TRIP_MAIN_COMPRESSOR_C101"]
        self.assertEqual(a.state, AlarmState.RTN_UNACK)
        p.acknowledge("TRIP_MAIN_COMPRESSOR_C101", "op1", t + 1)
        self.assertNotIn("TRIP_MAIN_COMPRESSOR_C101", p.active_alarms)

    def test_reconhecer_nao_resolve(self):
        p = novo_processador()
        _, t = sustentar(p, "PT_101", 92.0, T0)
        p.acknowledge("TRIP_MAIN_COMPRESSOR_C101", "op1", t)
        p.process_telemetry(SensorSignal("PT_101", 93.0, t + 1))
        a = p.active_alarms["TRIP_MAIN_COMPRESSOR_C101"]
        self.assertEqual(a.state, AlarmState.ACTIVE_ACK)
        self.assertEqual(len(p.operator_log), 1)
        self.assertEqual(p.operator_log[0]["operador"], "op1")

    def test_condicao_ativa_nao_duplica(self):
        p = novo_processador()
        _, t = sustentar(p, "PT_101", 92.0, T0)
        for i in range(10):
            self.assertIsNone(p.process_telemetry(SensorSignal("PT_101", 93.0 + i * 0.1, t + i)))
        self.assertEqual(p.counters["anunciados"], 1)

    def test_repeticao_reabre_mesma_linha(self):
        p = novo_processador()
        _, t = sustentar(p, "LT_201", 80.0, T0)
        p.acknowledge("HIGH_LEVEL_SEAL_OIL", "op1", t)
        p.process_telemetry(SensorSignal("LT_201", 60.0, t + 0.5))   # normaliza
        self.assertNotIn("HIGH_LEVEL_SEAL_OIL", p.active_alarms)
        sustentar(p, "LT_201", 80.0, t + 1.0)                          # volta dentro de 8 s
        a = p.active_alarms["HIGH_LEVEL_SEAL_OIL"]
        self.assertEqual(a.metadata["repeticoes"], 1)
        self.assertEqual(a.state, AlarmState.ACTIVE_UNACK)
        self.assertEqual(p.counters["anunciados"], 1)


class TestContextoEQualidade(unittest.TestCase):
    def test_P7_critico_nunca_suprimido_em_manutencao(self):
        """[P7] Na P1 o curinga '*' suprimia também o alarme CRÍTICO."""
        p = novo_processador()
        p.set_plant_state(PlantOperatingState.MAINTENANCE)
        alarm, _ = sustentar(p, "PT_101", 92.0, T0)
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.priority, AlarmPriority.CRITICAL)

    def test_supressao_contextual_registrada(self):
        p = novo_processador()
        p.set_plant_state(PlantOperatingState.MAINTENANCE)
        alarm, _ = sustentar(p, "LT_201", 80.0, T0)
        self.assertIsNone(alarm)
        self.assertGreaterEqual(p.counters["suprimidos_contexto"], 1)
        self.assertEqual(p.suppressed_log[0]["tag"], "HIGH_LEVEL_SEAL_OIL")

    def test_P8_qualidade_ruim_gera_alarme_de_instrumento(self):
        """[P8] Na P1 o sinal ruim era descartado sem aviso ao operador."""
        p = novo_processador()
        a = p.process_telemetry(SensorSignal("PT_101", 0.0, T0, quality_good=False))
        self.assertIsNotNone(a)
        self.assertEqual(a.tag, "TRIP_MAIN_COMPRESSOR_C101__QUALIDADE")
        self.assertEqual(a.priority, AlarmPriority.HIGH)
        # repetição do sinal ruim não duplica
        self.assertIsNone(p.process_telemetry(SensorSignal("PT_101", 0.0, T0 + 1, quality_good=False)))
        # sinal volta a ser bom -> normalizado aguardando reconhecimento
        p.process_telemetry(SensorSignal("PT_101", 70.0, T0 + 2))
        self.assertEqual(p.active_alarms[a.tag].state, AlarmState.RTN_UNACK)


class TestCorrelacao(unittest.TestCase):
    def test_sintoma_depois_da_causa_rebaixado(self):
        p = novo_processador()
        _, t = sustentar(p, "PT_101", 92.0, T0)
        flow, _ = sustentar(p, "FT_102", 30.0, t)
        self.assertEqual(flow.priority, AlarmPriority.LOW)
        self.assertEqual(flow.root_cause_tag, "TRIP_MAIN_COMPRESSOR_C101")
        self.assertEqual(flow.metadata["prioridade_original"], "HIGH")
        self.assertIn("LOW_FLOW_STAGE1", p.active_alarms["TRIP_MAIN_COMPRESSOR_C101"].metadata["sintomas"])

    def test_P9_sintoma_antes_da_causa_rebaixado_retroativamente(self):
        """[P9] Na P1 o sintoma que chegava primeiro ficava com prioridade HIGH."""
        p = novo_processador()
        _, t = sustentar(p, "FT_102", 30.0, T0)
        self.assertEqual(p.active_alarms["LOW_FLOW_STAGE1"].priority, AlarmPriority.HIGH)
        sustentar(p, "PT_101", 92.0, t)
        sym = p.active_alarms["LOW_FLOW_STAGE1"]
        self.assertEqual(sym.priority, AlarmPriority.LOW)
        self.assertEqual(sym.root_cause_tag, "TRIP_MAIN_COMPRESSOR_C101")

    def test_ordenacao_para_ihm(self):
        p = novo_processador()
        _, t = sustentar(p, "LT_201", 80.0, T0)
        _, t = sustentar(p, "PT_101", 92.0, t)
        ordem = [a.tag for a in p.get_sorted_active()]
        self.assertEqual(ordem[0], "TRIP_MAIN_COMPRESSOR_C101")


class TestMonitores(unittest.TestCase):
    def test_percentis(self):
        m = LatencyMonitor()
        for v in [10, 20, 30, 40, 50]:
            m.record_latency(AlarmPriority.HIGH, v)
        self.assertEqual(m.calculate_percentile(AlarmPriority.HIGH, 50), 30)
        self.assertAlmostEqual(m.calculate_percentile(AlarmPriority.HIGH, 95), 48.0)

    def test_demonstracao_original_da_p1_continua_passando(self):
        run_comprehensive_industrial_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
