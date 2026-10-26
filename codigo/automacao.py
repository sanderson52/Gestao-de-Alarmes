"""
MÓDULO DE ENGENHARIA DE GESTÃO DE ALARMES INDUSTRIAIS
Inspirado nos conceitos da ANSI/ISA-18.2-2016 / IEC 62682:2022 e na filosofia
de IHM de alto desempenho da ANSI/ISA-101.01-2015.
Linguagem: Python 3.9+ (zero dependências externas)

AVISO ACADÊMICO: este código é uma SIMULAÇÃO DIDÁTICA (disciplina COM8 - IUM/IHM).
Não foi validado em planta industrial real e não declara conformidade com
nenhuma norma. Os nomes de tags e o grafo causal são fictícios.

HISTÓRICO DE CORREÇÕES
P1 (versão original, set/2026):
[1] Strings de log reescritas em linha única (elimina SyntaxError de cópia)
[2] AntiChatteringFilter com direção HI/LO (corrige semântica de alarmes de mínimo)
[3] Supressão de alarme duplicado enquanto a condição já está ativa
[4] Testes ajustados para respeitar a semântica HI/LO correta

P2 (out/2026) - erros reproduzidos e corrigidos (ver test_automacao.py):
[5] Retorno ao normal: na P1 o "return" antecipado da correção [3] impedia que
    o alarme saísse da lista de ativos (código de normalização inalcançável).
[6] Deduplicação: o horário padrão 0.0 suprimia o PRIMEIRO alarme de qualquer
    sinal com timestamp < janela (ex.: relógio de simulação iniciando em 0 s).
    Repetições dentro da janela agora REABREM o mesmo registro e incrementam
    um contador, em vez de descartar o alarme silenciosamente.
[7] Inibição contextual segura: o curinga "*" do modo MAINTENANCE suprimia até
    alarmes CRÍTICOS. Alarmes CRÍTICOS nunca são suprimidos por contexto, e toda
    supressão fica registrada e consultável (não é "apagada").
[8] Qualidade de sinal: um sinal com qualidade ruim era descartado sem aviso.
    Agora gera um alarme de instrumento ("valor não confiável").
[9] Correlação retroativa: um sintoma que chegava ANTES da causa-raiz não era
    rebaixado. Agora a correlação é reavaliada para todos os alarmes ativos.
[10] Ciclo de vida do alarme: estados ATIVO NÃO RECONHECIDO, ATIVO RECONHECIDO e
    NORMALIZADO NÃO RECONHECIDO; método acknowledge() com registro do operador.
    Reconhecer NÃO resolve o alarme: só sai da lista quando o processo normaliza.
[11] Campos para a IHM: ação recomendada, unidade de engenharia, equipamento,
    contador de repetições e alarmes relacionados.
"""

import time
import math
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import IntEnum, Enum

# Configuração de Logging Estruturado para Ambiente Industrial
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("IndustrialAlarmEngine")

# ============================================================
# 1. ENUMERAÇÕES E ESTRUTURAS DE DADOS FORMALIZADAS
# ============================================================

class AlarmPriority(IntEnum):
    """
    Níveis de prioridade adotados neste projeto. A ISA-18.2 orienta usar
    poucos níveis, definidos na filosofia de alarmes da planta; esta escala
    de 4 níveis + diagnóstico é uma escolha de projeto, não uma exigência normativa.
    """
    DIAGNOSTIC = 0   # Log / Diagnóstico interno (não anunciado ao operador)
    LOW = 1          # P4 - Baixa relevância operacional
    MEDIUM = 2       # P3 - Médio impacto
    HIGH = 3         # P2 - Alto impacto
    CRITICAL = 4     # P1 - Risco à segurança


class AlarmState(str, Enum):
    """Estados do ciclo de vida usados na IHM (subconjunto do modelo ISA-18.2)."""
    NORMAL = "NORMAL"
    ACTIVE_UNACK = "ATIVO_NAO_RECONHECIDO"
    ACTIVE_ACK = "ATIVO_RECONHECIDO"
    RTN_UNACK = "NORMALIZADO_NAO_RECONHECIDO"


class PlantOperatingState(IntEnum):
    """Modos de operação da planta para filtragem contextual."""
    NORMAL_OPERATION = 1
    STARTUP = 2
    SHUTDOWN = 3
    MAINTENANCE = 4
    EMERGENCY_TRIP = 5


@dataclass
class AlarmMessage:
    """Estrutura formal de um alarme processado e acionável."""
    alarm_id: str
    sensor_id: str
    value: float
    setpoint: float
    priority: AlarmPriority
    timestamp: float
    description: str
    root_cause_tag: Optional[str] = None
    acknowledged: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Campos adicionados na P2 (com valores padrão para manter compatibilidade)
    tag: str = ""
    state: AlarmState = AlarmState.ACTIVE_UNACK
    recommended_action: str = ""
    unit: str = ""
    equipment: str = ""
    direction: str = "HI"

    def to_dict(self) -> Dict[str, Any]:
        """Representação serializável (JSON) usada pela IHM."""
        return {
            "alarm_id": self.alarm_id,
            "tag": self.tag,
            "sensor_id": self.sensor_id,
            "equipment": self.equipment,
            "value": round(self.value, 2) if self.value is not None else None,
            "setpoint": self.setpoint,
            "unit": self.unit,
            "direction": self.direction,
            "priority": self.priority.name,
            "priority_level": int(self.priority),
            "timestamp": self.timestamp,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "state": self.state.value,
            "acknowledged": self.acknowledged,
            "root_cause_tag": self.root_cause_tag,
            "metadata": dict(self.metadata),
        }


@dataclass
class SensorSignal:
    """Estrutura do pacote de telemetria bruto recebido de campo."""
    sensor_id: str
    value: float
    timestamp: float
    quality_good: bool = True

# ============================================================
# 2. FILTROS INDIVIDUAIS DA ARQUITETURA EM CASCATA
# ============================================================

class AntiChatteringFilter:
    """
    Filtro de ruído com histerese (deadband) na desativação e temporização
    on-delay na ativação. Suporta direção HI (dispara acima do limite) e
    LO (dispara abaixo do limite), com histerese coerente para cada caso.
    """
    def __init__(self, deadband_percent: float = 0.02, on_delay_sec: float = 2.0):
        self.deadband_percent = deadband_percent
        self.on_delay_sec = on_delay_sec
        self.state_active: Dict[str, bool] = {}
        self.first_exceed_time: Dict[str, Optional[float]] = {}

    def evaluate(self, sensor_id: str, value: float, limit: float,
                 span: float, timestamp: float, direction: str = "HI") -> bool:
        """
        Determina se o sinal ultrapassou o limiar de forma estável e sustentada.
        direction: "HI" = alarme de máximo (value > limit)
                   "LO" = alarme de mínimo (value < limit)
        """
        deadband_val = span * self.deadband_percent

        if direction == "HI":
            is_exceeding = value > limit
            clear_condition = value < (limit - deadband_val)
        elif direction == "LO":
            is_exceeding = value < limit
            clear_condition = value > (limit + deadband_val)
        else:
            raise ValueError(f"Direção de alarme inválida: {direction}. Use 'HI' ou 'LO'.")

        was_active = self.state_active.get(sensor_id, False)

        # Histerese de desativação: só limpa fora da faixa morta
        if was_active:
            if clear_condition:
                self.state_active[sensor_id] = False
                self.first_exceed_time[sensor_id] = None
                logger.debug(f"[AntiChatter] Sensor {sensor_id} retornou à faixa segura com histerese.")
                return False
            return True

        # On-Delay para ativação: exige sustentação da violação
        if is_exceeding:
            first_time = self.first_exceed_time.get(sensor_id)
            if first_time is None:
                self.first_exceed_time[sensor_id] = timestamp
                logger.debug(f"[AntiChatter] Sensor {sensor_id} excedeu limite. Aguardando On-Delay...")
                return False

            elapsed = timestamp - first_time
            if elapsed >= self.on_delay_sec:
                self.state_active[sensor_id] = True
                logger.info(f"[AntiChatter] Sensor {sensor_id} confirmou violação de limite após {elapsed:.2f}s.")
                return True
            return False
        else:
            self.first_exceed_time[sensor_id] = None
            return False


class DeduplicationFilter:
    """
    Filtro de Redundância e Agrupamento Temporal.
    Garante que ocorrências repetidas da mesma condição não criem novas linhas.
    CORREÇÃO [6]: ausência de histórico não é mais tratada como horário 0.0.
    """
    def __init__(self, suppression_window_sec: float = 10.0):
        self.window = suppression_window_sec
        self.last_alarm_time: Dict[str, float] = {}

    def should_suppress(self, alarm_key: str, timestamp: float) -> bool:
        last_time = self.last_alarm_time.get(alarm_key)
        if last_time is not None and (timestamp - last_time) < self.window:
            logger.debug(f"[Deduplication] Alarme {alarm_key} agrupado por repetição dentro da janela de {self.window}s.")
            return True
        self.last_alarm_time[alarm_key] = timestamp
        return False


class ContextualFilter:
    """
    Filtro de Estado da Planta. Suprime alarmes esperados em regimes transitórios.
    CORREÇÃO [7]: alarmes CRÍTICOS nunca são inibidos por contexto.
    """
    def __init__(self):
        self.suppressed_by_state: Dict[PlantOperatingState, List[str]] = {
            PlantOperatingState.STARTUP: ["LOW_FLOW_P101", "LOW_PRESSURE_T200", "TEMP_GRADIENT_C1"],
            PlantOperatingState.SHUTDOWN: ["LOW_FLOW_P101", "MOTOR_STOPPED_M102", "ZERO_PRESSURE_SYSTEM"],
            PlantOperatingState.MAINTENANCE: ["*"]
        }

    def is_suppressed(self, tag_id: str, state: PlantOperatingState,
                      priority: AlarmPriority = AlarmPriority.LOW) -> bool:
        if priority >= AlarmPriority.CRITICAL:
            return False
        suppressed_tags = self.suppressed_by_state.get(state, [])
        if "*" in suppressed_tags or tag_id in suppressed_tags:
            logger.info(f"[ContextualFilter] Alarme {tag_id} inibido pelo modo: {state.name} (registrado).")
            return True
        return False


class RootCauseCorrelator:
    """
    Grafo Causal Simples para Agrupamento Topológico de Sintomas Dependentes.
    Identifica o nó primário e rebaixa as notificações consequentes.
    """
    def __init__(self):
        self.causal_graph: Dict[str, List[str]] = {
            "TRIP_MAIN_COMPRESSOR_C101": [
                "LOW_FLOW_STAGE1",
                "PRESSURE_DROP_HEADER",
                "TEMP_RISE_INTERCOOLER",
                "BEARING_TEMP_FALL_C101"
            ],
            "POWER_BUS_FAILURE_SWG01": [
                "PUMP_P101A_STOPPED",
                "PUMP_P101B_STOPPED",
                "COOLING_FAN_TRIP",
                "UPS_ON_BATTERY"
            ]
        }

    def correlate(self, active_alarm_tags: List[str]) -> Tuple[List[str], Dict[str, str]]:
        """
        Retorna:
        - primary_alarms: causas-raiz que devem ser exibidas com alta prioridade.
        - secondary_map: mapeamento sintoma -> causa raiz.
        """
        primary = []
        secondary_map = {}
        active_set = set(active_alarm_tags)

        for root_cause, symptoms in self.causal_graph.items():
            if root_cause in active_set:
                primary.append(root_cause)
                for symptom in symptoms:
                    if symptom in active_set:
                        secondary_map[symptom] = root_cause

        # Tags ativas que não são sintomas de nenhuma causa detectada
        for tag in active_alarm_tags:
            if tag not in secondary_map and tag not in primary:
                primary.append(tag)

        return primary, secondary_map

# ============================================================
# 3. MOTOR PRINCIPAL UNIFICADO: AlarmProcessor
# ============================================================

class AlarmProcessor:
    """
    Processador Central de Engenharia de Alarmes Industriais.
    Integra toda a cadeia de filtragem, priorização e roteamento.
    """
    def __init__(self):
        self.anti_chatter = AntiChatteringFilter(deadband_percent=0.02, on_delay_sec=1.5)
        self.dedup = DeduplicationFilter(suppression_window_sec=8.0)
        self.context_filter = ContextualFilter()
        self.correlator = RootCauseCorrelator()

        # sensor_id -> {limit, span, priority, description, tag, direction, ...}
        self.configured_limits: Dict[str, Dict[str, Any]] = {}
        self.active_alarms: Dict[str, AlarmMessage] = {}
        self.last_alarm_by_tag: Dict[str, AlarmMessage] = {}
        self.current_plant_state: PlantOperatingState = PlantOperatingState.NORMAL_OPERATION

        # Rastreabilidade (P2): eventos do sistema, ações do operador, supressões
        self.event_log: List[Dict[str, Any]] = []
        self.operator_log: List[Dict[str, Any]] = []
        self.suppressed_log: List[Dict[str, Any]] = []
        self.counters: Dict[str, int] = {
            "anunciados": 0,
            "suprimidos_contexto": 0,
            "repeticoes_agrupadas": 0,
            "rebaixados_correlacao": 0,
            "qualidade_ruim": 0,
            "normalizados": 0,
            "reconhecidos": 0,
        }
        self._last_ts: float = 0.0

    # ---------------- configuração ----------------

    def set_plant_state(self, state: PlantOperatingState) -> None:
        logger.warning(f"[AlarmProcessor] Estado operacional da planta alterado para: {state.name}")
        self.current_plant_state = state
        self._log_event(self._last_ts, "-", "MODO_PLANTA", state.name)

    def configure_alarm_tag(self, sensor_id: str, tag: str, limit: float, span: float,
                            priority: AlarmPriority, description: str,
                            direction: str = "HI", recommended_action: str = "",
                            unit: str = "", equipment: str = "") -> None:
        """CORREÇÃO [2]: parâmetro 'direction' para alarmes HI (máximo) ou LO (mínimo).
        P2: parâmetros opcionais para a IHM (ação recomendada, unidade, equipamento)."""
        if direction not in ("HI", "LO"):
            raise ValueError(f"Direção inválida para {tag}: {direction}")
        self.configured_limits[sensor_id] = {
            "tag": tag,
            "limit": limit,
            "span": span,
            "priority": priority,
            "description": description,
            "direction": direction,
            "recommended_action": recommended_action,
            "unit": unit,
            "equipment": equipment,
        }
        logger.info(f"[Config] Tag '{tag}' configurada (sensor {sensor_id}, limite {limit}, dir {direction}, prio {priority.name}).")

    # ---------------- registro ----------------

    def _log_event(self, ts: float, tag: str, event: str, detail: str = "") -> None:
        self.event_log.append({"timestamp": ts, "tag": tag, "evento": event, "detalhe": detail})

    # ---------------- ciclo de vida ----------------

    def _return_to_normal(self, tag: str, ts: float) -> None:
        alarm = self.active_alarms.get(tag)
        if alarm is None:
            return
        if alarm.state == AlarmState.ACTIVE_ACK:
            alarm.state = AlarmState.NORMAL
            del self.active_alarms[tag]
            self.counters["normalizados"] += 1
            self._log_event(ts, tag, "NORMALIZADO", "condição cessou; alarme já reconhecido sai da lista")
            logger.info(f"[AlarmProcessor] Alarme {tag} NORMALIZADO pelo processo.")
        elif alarm.state == AlarmState.ACTIVE_UNACK:
            alarm.state = AlarmState.RTN_UNACK
            self._log_event(ts, tag, "NORMALIZADO_SEM_RECONHECIMENTO", "aguarda reconhecimento do operador")
            logger.info(f"[AlarmProcessor] Alarme {tag} normalizou sem reconhecimento.")

    def acknowledge(self, tag: str, operator: str = "operador",
                    timestamp: Optional[float] = None, note: str = "") -> bool:
        """
        CORREÇÃO [10]: reconhecimento humano. Reconhecer indica que o operador
        tomou ciência; NÃO resolve a condição. Retorna True se houve mudança.
        """
        ts = self._last_ts if timestamp is None else timestamp
        alarm = self.active_alarms.get(tag)
        if alarm is None or alarm.state not in (AlarmState.ACTIVE_UNACK, AlarmState.RTN_UNACK):
            return False
        alarm.acknowledged = True
        if alarm.state == AlarmState.ACTIVE_UNACK:
            alarm.state = AlarmState.ACTIVE_ACK
            result = "ATIVO_RECONHECIDO (condição permanece)"
        else:
            alarm.state = AlarmState.NORMAL
            del self.active_alarms[tag]
            self.counters["normalizados"] += 1
            result = "NORMAL (já havia normalizado)"
        self.counters["reconhecidos"] += 1
        entry = {"timestamp": ts, "tag": tag, "operador": operator, "acao": "RECONHECER",
                 "resultado": result, "observacao": note}
        self.operator_log.append(entry)
        self._log_event(ts, tag, "RECONHECIDO", f"{operator}: {result}")
        logger.info(f"[Operador] {operator} reconheceu {tag} -> {result}")
        return True

    # ---------------- correlação ----------------

    def _update_correlation(self) -> None:
        """CORREÇÃO [9]: reavalia todos os ativos (sintoma pode chegar antes da causa)."""
        # Inclui alarmes normalizados ainda não reconhecidos: uma causa-raiz que
        # acabou de passar (ex.: trip) continua explicando seus sintomas.
        active_tags = list(self.active_alarms.keys())
        _, secondary_map = self.correlator.correlate(active_tags)
        roots: Dict[str, List[str]] = {}
        for symptom, root in secondary_map.items():
            roots.setdefault(root, []).append(symptom)
            alarm = self.active_alarms[symptom]
            if alarm.root_cause_tag != root:
                alarm.metadata.setdefault("prioridade_original", alarm.priority.name)
                alarm.root_cause_tag = root
                alarm.priority = AlarmPriority.LOW
                self.counters["rebaixados_correlacao"] += 1
                self._log_event(alarm.timestamp, symptom, "CORRELACIONADO",
                                f"sintoma de {root}; prioridade {alarm.metadata['prioridade_original']} -> LOW")
                logger.info(f"[Correlator] Sintoma '{symptom}' correlacionado à causa raiz '{root}'.")
        for root, symptoms in roots.items():
            if root in self.active_alarms:
                self.active_alarms[root].metadata["sintomas"] = sorted(symptoms)

    # ---------------- qualidade de sinal ----------------

    def _handle_bad_quality(self, signal: SensorSignal, cfg: Dict[str, Any]) -> Optional[AlarmMessage]:
        """CORREÇÃO [8]: sinal ruim gera alarme de instrumento, não silêncio."""
        qtag = f"{cfg['tag']}__QUALIDADE"
        logger.error(f"[AlarmProcessor] Sinal com má qualidade: {signal.sensor_id}")
        if qtag in self.active_alarms:
            if self.active_alarms[qtag].state == AlarmState.RTN_UNACK:
                self.active_alarms[qtag].state = AlarmState.ACTIVE_UNACK
            return None
        prio = AlarmPriority.HIGH if cfg["priority"] >= AlarmPriority.CRITICAL else AlarmPriority.MEDIUM
        if self.context_filter.is_suppressed(qtag, self.current_plant_state, prio):
            self._register_suppression(qtag, signal.timestamp, "contexto")
            return None
        alarm = AlarmMessage(
            alarm_id=f"ALM_{qtag}_{int(signal.timestamp * 1000)}",
            sensor_id=signal.sensor_id, value=signal.value, setpoint=cfg["limit"],
            priority=prio, timestamp=signal.timestamp,
            description=f"Falha de instrumento {signal.sensor_id}: valor não confiável ({cfg['description']})",
            tag=qtag, unit=cfg.get("unit", ""), equipment=cfg.get("equipment", ""),
            direction=cfg["direction"],
            recommended_action="Não usar este valor para decidir. Verificar instrumento/cabo e acionar a instrumentação; confirmar a variável por medição redundante.",
            metadata={"tipo": "instrumento", "repeticoes": 0},
        )
        self.active_alarms[qtag] = alarm
        self.last_alarm_by_tag[qtag] = alarm
        self.counters["qualidade_ruim"] += 1
        self.counters["anunciados"] += 1
        self._log_event(signal.timestamp, qtag, "ANUNCIADO", "qualidade de sinal ruim")
        return alarm

    def _register_suppression(self, tag: str, ts: float, motivo: str) -> None:
        self.counters["suprimidos_contexto"] += 1
        self.suppressed_log.append({"timestamp": ts, "tag": tag, "motivo": motivo,
                                    "modo": self.current_plant_state.name})

    # ---------------- cadeia principal ----------------

    def process_telemetry(self, signal: SensorSignal) -> Optional[AlarmMessage]:
        """Executa a cadeia completa de filtragem determinística sobre a amostra.
        Retorna um AlarmMessage apenas quando uma NOVA anunciação é criada."""
        self._last_ts = signal.timestamp
        cfg = self.configured_limits.get(signal.sensor_id)
        if not cfg:
            return None

        tag = cfg["tag"]

        if not signal.quality_good:
            return self._handle_bad_quality(signal, cfg)
        # Sinal voltou a ser confiável: alarme de instrumento retorna ao normal
        self._return_to_normal(f"{tag}__QUALIDADE", signal.timestamp)

        # 1. Filtro de Ruído / Histerese / On-Delay (com direção HI/LO)
        is_violated = self.anti_chatter.evaluate(
            sensor_id=signal.sensor_id,
            value=signal.value,
            limit=cfg["limit"],
            span=cfg["span"],
            timestamp=signal.timestamp,
            direction=cfg["direction"]
        )

        existing = self.active_alarms.get(tag)
        if existing is not None:
            existing.value = signal.value  # valor ao vivo para a IHM
            if is_violated:
                # CORREÇÃO [3] preservada: condição já ativa não gera nova notificação
                if existing.state == AlarmState.RTN_UNACK:
                    existing.state = AlarmState.ACTIVE_UNACK
                    self._log_event(signal.timestamp, tag, "REATIVADO", "voltou a violar antes do reconhecimento")
                return None
            # CORREÇÃO [5]: normalização agora é alcançável
            self._return_to_normal(tag, signal.timestamp)
            return None

        if not is_violated:
            return None

        # 2. Filtro Contextual (Modos de Operação) - nunca para CRÍTICOS
        if self.context_filter.is_suppressed(tag, self.current_plant_state, cfg["priority"]):
            self._register_suppression(tag, signal.timestamp, "contexto")
            return None

        # 3. Deduplicação Temporal: repetição reabre o mesmo registro (CORREÇÃO [6])
        if self.dedup.should_suppress(tag, signal.timestamp):
            prev = self.last_alarm_by_tag.get(tag)
            if prev is not None:
                prev.state = AlarmState.ACTIVE_UNACK
                prev.acknowledged = False
                prev.value = signal.value
                prev.metadata["repeticoes"] = prev.metadata.get("repeticoes", 0) + 1
                self.active_alarms[tag] = prev
                self.counters["repeticoes_agrupadas"] += 1
                self._log_event(signal.timestamp, tag, "REPETICAO_AGRUPADA",
                                f"ocorrência nº {prev.metadata['repeticoes'] + 1} na mesma linha")
                self._update_correlation()
            return None

        # Criação da Estrutura Base do Alarme
        alarm = AlarmMessage(
            alarm_id=f"ALM_{tag}_{int(signal.timestamp * 1000)}",
            sensor_id=signal.sensor_id,
            value=signal.value,
            setpoint=cfg["limit"],
            priority=cfg["priority"],
            timestamp=signal.timestamp,
            description=cfg["description"],
            tag=tag,
            recommended_action=cfg.get("recommended_action", ""),
            unit=cfg.get("unit", ""),
            equipment=cfg.get("equipment", ""),
            direction=cfg["direction"],
            metadata={"repeticoes": 0},
        )
        self.active_alarms[tag] = alarm
        self.last_alarm_by_tag[tag] = alarm
        self.counters["anunciados"] += 1
        self._log_event(signal.timestamp, tag, "ANUNCIADO",
                        f"{signal.value:.1f} {cfg.get('unit', '')} vs limite {cfg['limit']} ({cfg['direction']})")

        # 4. Correlação Topológica e Atualização de Causa Raiz
        self._update_correlation()
        if alarm.root_cause_tag:
            logger.info(f"[AlarmProcessor] Alarme {tag} associado como sintoma da causa raiz {alarm.root_cause_tag}.")

        return alarm

    def get_sorted_active(self) -> List[AlarmMessage]:
        """Lista para a IHM: não reconhecidos primeiro, depois prioridade e horário."""
        def key(a: AlarmMessage):
            unack = a.state in (AlarmState.ACTIVE_UNACK, AlarmState.RTN_UNACK)
            return (0 if unack else 1, -int(a.priority), a.timestamp)
        return sorted(self.active_alarms.values(), key=key)

# ============================================================
# 4. MONITORAMENTO DE PERFORMANCE E CRITÉRIOS DE QUALIDADE
# ============================================================

class LatencyMonitor:
    """Cálculo de latência percentilar (P50, P95, P99) por prioridade."""
    def __init__(self):
        self.latencies_by_priority: Dict[AlarmPriority, List[float]] = {
            p: [] for p in AlarmPriority
        }

    def record_latency(self, priority: AlarmPriority, latency_ms: float) -> None:
        if latency_ms < 0:
            logger.warning(f"[LatencyMonitor] Latência negativa ignorada: {latency_ms}ms")
            return
        self.latencies_by_priority[priority].append(latency_ms)

    def calculate_percentile(self, priority: AlarmPriority, percentile: float) -> float:
        records = sorted(self.latencies_by_priority[priority])
        if not records:
            return 0.0
        if len(records) == 1:
            return records[0]

        k = (len(records) - 1) * (percentile / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return records[int(k)]
        d0 = records[int(f)] * (c - k)
        d1 = records[int(c)] * (k - f)
        return d0 + d1

    def get_summary(self) -> Dict[str, Dict[str, float]]:
        summary = {}
        for prio in AlarmPriority:
            summary[prio.name] = {
                "count": len(self.latencies_by_priority[prio]),
                "p50_ms": round(self.calculate_percentile(prio, 50), 2),
                "p95_ms": round(self.calculate_percentile(prio, 95), 2),
                "p99_ms": round(self.calculate_percentile(prio, 99), 2),
            }
        return summary


class ErrorRateMonitor:
    """Validador de Integridade: audita falsos positivos, negativos e SLA."""
    def __init__(self):
        self.total_evaluations: int = 0
        self.false_positives: int = 0
        self.false_negatives: int = 0
        self.timing_violations: int = 0

    def evaluate_transaction(self, generated_by_new_system: bool,
                             expected_by_reference: bool,
                             latency_ms: float,
                             max_allowed_latency_ms: float = 500.0) -> None:
        self.total_evaluations += 1

        if generated_by_new_system and not expected_by_reference:
            self.false_positives += 1
            logger.debug("[ErrorAudit] Falso Positivo computado.")
        elif not generated_by_new_system and expected_by_reference:
            self.false_negatives += 1
            logger.error("[ErrorAudit] CRÍTICO: Falso Negativo computado (alarme omitido).")

        if generated_by_new_system and latency_ms > max_allowed_latency_ms:
            self.timing_violations += 1
            logger.warning(f"[ErrorAudit] Violação de SLA de latência: {latency_ms}ms > {max_allowed_latency_ms}ms.")

    def get_error_metrics(self) -> Dict[str, float]:
        if self.total_evaluations == 0:
            return {"false_positive_rate_%": 0.0, "false_negative_rate_%": 0.0, "sla_violation_rate_%": 0.0}
        return {
            "total_evaluations": self.total_evaluations,
            "false_positive_rate_%": round((self.false_positives / self.total_evaluations) * 100, 4),
            "false_negative_rate_%": round((self.false_negatives / self.total_evaluations) * 100, 4),
            "sla_violation_rate_%": round((self.timing_violations / self.total_evaluations) * 100, 4),
        }


class QualityAlertEngine:
    """Motor de Governança: dispara alertas se indicadores violarem metas."""
    def __init__(self, max_p95_critical_latency_ms: float = 200.0,
                 max_false_neg_rate_percent: float = 0.01):
        self.max_latency_p1 = max_p95_critical_latency_ms
        self.max_fn_rate = max_false_neg_rate_percent

    def audit_performance(self, latency_summary: Dict[str, Any],
                          error_metrics: Dict[str, Any]) -> List[str]:
        health_warnings = []

        critical_p95 = latency_summary.get("CRITICAL", {}).get("p95_ms", 0.0)
        if critical_p95 > self.max_latency_p1:
            msg = f"[ALERTA QUALIDADE] Latência P95 Crítica excedida: {critical_p95}ms (Meta: <{self.max_latency_p1}ms)"
            health_warnings.append(msg)
            logger.error(msg)

        fn_rate = error_metrics.get("false_negative_rate_%", 0.0)
        if fn_rate > self.max_fn_rate:
            msg = f"[ALERTA QUALIDADE SEVERO] Taxa de Falsos Negativos inaceitável: {fn_rate}% (Meta: <{self.max_fn_rate}%)"
            health_warnings.append(msg)
            logger.critical(msg)

        if not health_warnings:
            logger.info("[QualityAlertEngine] Todos os critérios de qualidade foram satisfeitos.")

        return health_warnings

# ============================================================
# 5. DEMONSTRAÇÃO ORIGINAL DA P1 (mantida)
# ============================================================

def run_comprehensive_industrial_test():
    """
    Demonstração original da P1 (mantida para continuidade).
    Os testes automatizados completos estão em test_automacao.py.
    Observação: as latências desta demonstração incluem um acréscimo FIXO
    simulado (+12 ms / +45 ms); não são medições de um barramento real.
    """
    logger.info("=" * 60)
    logger.info("INICIANDO SUÍTE INTEGRADA DE TESTE DE GESTÃO DE ALARMES")
    logger.info("=" * 60)

    processor = AlarmProcessor()
    latency_monitor = LatencyMonitor()
    error_monitor = ErrorRateMonitor()
    quality_engine = QualityAlertEngine(max_p95_critical_latency_ms=200.0, max_false_neg_rate_percent=0.01)

    processor.configure_alarm_tag(
        sensor_id="PT_101", tag="TRIP_MAIN_COMPRESSOR_C101",
        limit=85.0, span=100.0, priority=AlarmPriority.CRITICAL,
        description="Pressão de Descarga Crítica - Trip do Compressor C101",
        direction="HI"
    )
    processor.configure_alarm_tag(
        sensor_id="FT_102", tag="LOW_FLOW_STAGE1",
        limit=40.0, span=100.0, priority=AlarmPriority.HIGH,
        description="Baixa Vazão de Sucção do Estágio 1",
        direction="LO"
    )
    processor.configure_alarm_tag(
        sensor_id="LT_201", tag="HIGH_LEVEL_SEAL_OIL",
        limit=75.0, span=100.0, priority=AlarmPriority.MEDIUM,
        description="Nível Elevado do Vaso de Óleo de Selagem",
        direction="HI"
    )

    current_time = 1700000000.0

    logger.info("--- CENÁRIO 1: Teste de Anti-Chattering e Histerese (LT_201) ---")
    samples = [75.2, 74.8, 75.4, 74.9, 75.5]
    for i, val in enumerate(samples):
        current_time += 0.2
        t0 = time.perf_counter()
        sig = SensorSignal(sensor_id="LT_201", value=val, timestamp=current_time)
        res = processor.process_telemetry(sig)
        lat_ms = (time.perf_counter() - t0) * 1000 + 12.0  # latência simulada de barramento
        assert res is None, f"Falha: Alarme instável não suprimido na amostra {i}"
        latency_monitor.record_latency(AlarmPriority.MEDIUM, lat_ms)
        error_monitor.evaluate_transaction(
            generated_by_new_system=(res is not None),
            expected_by_reference=False,
            latency_ms=lat_ms
        )
    logger.info("Sucesso: Nenhuma notificação espúria gerada pelo ruído transiente.")

    current_time += 1.6
    sig_sustained = SensorSignal(sensor_id="LT_201", value=76.0, timestamp=current_time)
    res_sustained = processor.process_telemetry(sig_sustained)
    assert res_sustained is not None, "Falha: Alarme sustentado deveria ter sido gerado."
    assert res_sustained.priority == AlarmPriority.MEDIUM
    logger.info(f"Sucesso: Alarme ativado após on-delay: {res_sustained.alarm_id}")

    logger.info("--- CENÁRIO 2: Trip Crítico com Correlação de Sintomas ---")
    current_time += 5.0
    processor.process_telemetry(SensorSignal(sensor_id="PT_101", value=92.0, timestamp=current_time))
    current_time += 1.6
    t_start = time.perf_counter()
    trip_alarm = processor.process_telemetry(SensorSignal(sensor_id="PT_101", value=93.5, timestamp=current_time))
    lat_p1 = (time.perf_counter() - t_start) * 1000 + 45.0
    assert trip_alarm is not None
    assert trip_alarm.priority == AlarmPriority.CRITICAL
    latency_monitor.record_latency(AlarmPriority.CRITICAL, lat_p1)
    error_monitor.evaluate_transaction(True, True, lat_p1)
    logger.info(f"Alarme Mestre Ativado: {trip_alarm.description} | Prio: {trip_alarm.priority.name}")

    processor.process_telemetry(SensorSignal(sensor_id="FT_102", value=35.0, timestamp=current_time))
    current_time += 1.6
    flow_alarm = processor.process_telemetry(SensorSignal(sensor_id="FT_102", value=38.0, timestamp=current_time))
    assert flow_alarm is not None, "Falha: Alarme de vazão mínima sustentado não foi gerado."
    assert flow_alarm.priority == AlarmPriority.LOW
    assert flow_alarm.root_cause_tag == "TRIP_MAIN_COMPRESSOR_C101"
    logger.info(f"Sintoma Rebaixado com Sucesso: {flow_alarm.description}")
    logger.info(f"-> Causa Raiz: {flow_alarm.root_cause_tag} (Prioridade: {flow_alarm.priority.name})")

    current_time += 2.0
    dup_result = processor.process_telemetry(SensorSignal(sensor_id="PT_101", value=94.0, timestamp=current_time))
    assert dup_result is None, "Falha: Alarme duplicado gerado para condição já ativa."
    logger.info("Sucesso: Nenhuma duplicação para condição de alarme já ativa.")

    logger.info("--- CENÁRIO 3: Consolidação e Auditoria de Métricas ---")
    latency_summary = latency_monitor.get_summary()
    error_metrics = error_monitor.get_error_metrics()
    logger.info(f"Sumário de Latências (Percentis): {latency_summary}")
    logger.info(f"Métricas de Auditoria de Erro: {error_metrics}")
    quality_alerts = quality_engine.audit_performance(latency_summary, error_metrics)
    assert len(quality_alerts) == 0, f"Falha: Não-conformidades reportadas: {quality_alerts}"

    logger.info("=" * 60)
    logger.info("TODOS OS TESTES DE ENGENHARIA FORAM CONCLUÍDOS COM SUCESSO")
    logger.info("=" * 60)

# ============================================================
# 6. PONTO DE ENTRADA E GUIA DE DEBUG
# ============================================================

if __name__ == "__main__":
    # Debug detalhado: descomente a linha abaixo para trace de cada decisão lógica
    # logger.setLevel(logging.DEBUG)

    # Para novos nós causais: atualize 'causal_graph' em RootCauseCorrelator
    # Para integração real (MQTT/OPC-UA): empacote payloads em SensorSignal
    run_comprehensive_industrial_test()
