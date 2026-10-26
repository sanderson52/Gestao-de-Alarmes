# AlarmFlow — Gestão de alarmes e IHM de alto desempenho (C-101)

> Motor de racionalização de alarmes ISA-18.2 com IHM ISA-101

**Disciplina:** COM8 · IUM/IHM — Projeto P2
**Tecnologias:** Python 3.9+ (biblioteca padrão), HTML, CSS e JavaScript

---

## Resumo

Sistemas de alarme mal configurados geram mais notificações do que o operador consegue
processar, e o alarme relevante se perde no ruído. Este projeto implementa um motor de
gestão de alarmes e uma Interface Homem-Máquina (IHM) para um compressor de gás
**fictício** (C-101). O motor filtra ruído, agrupa consequências sob a causa-raiz e sinaliza
falhas de instrumento. A IHM compara, sobre os mesmos dados, uma tela sem tratamento
(A) e uma tela com o motor (B).

Na simulação, as notificações caem de **109 para 5** (redução de 95,4 %), sem perda de
alarmes críticos.

> Projeto acadêmico. Os dados são simulados. As normas ISA-18.2, IEC 62682 e ISA-101 são
> usadas como referência conceitual; não há declaração de conformidade nem validação em planta real.

---

## Entrega

| Exigência | Atendimento |
|---|---|
| Nova versão do trabalho escrito | Este documento, que complementa o texto da P1. |
| Apresentação em slides | [`Gestão de Alarmes – Compressor C-101.pptx`](./Gestão%20de%20Alarmes%20–%20Compressor%20C-101.pptx) (9 slides). |
| Entrega até 23/10, às 19h | Slides, este texto e o código em [`codigo/`](./codigo). |

---

## Como abrir a interface para testar

### 1. Pré-requisito

Python 3.9 ou superior ([python.org](https://www.python.org/downloads/)). No Windows, marque
**"Add python.exe to PATH"** durante a instalação. Não há bibliotecas a instalar.

### 2. Obter o projeto

```bash
git clone https://github.com/BrunoSilveira100/alarmflow-c101.git
cd alarmflow-c101/codigo
```

Também é possível baixar o ZIP pelo botão **Code → Download ZIP** no GitHub e extraí-lo.

### 3. Iniciar a IHM

Escolha **uma** das opções:

- **Windows (mais simples):** abra a pasta `codigo` e dê um duplo clique em `executar_ihm.bat`.
- **Terminal:** dentro da pasta `codigo`, execute `python servidor_ihm.py`.
- **VS Code:** abra a pasta `codigo`, pressione `Ctrl+Shift+D` e execute a configuração
  *"IHM de alarmes (servidor + navegador)"*.

O navegador abre sozinho em **http://localhost:8000**. Se não abrir, digite esse endereço
manualmente. Mantenha a janela do terminal aberta enquanto testa; para encerrar, feche-a ou
pressione `Ctrl+C`.

### 4. Roteiro de teste (cerca de 3 minutos)

| Passo | Ação | Resultado esperado |
|---|---|---|
| 1 | Com a visão **A + B** selecionada, clique em **▶ Reproduzir**. | A tela A acumula alarmes do nível do vaso V-201, que oscila no limite. A tela B permanece vazia, pois o ruído é filtrado. |
| 2 | Clique em **⏭ Ir para o trip**. | Na tela B surge 1 alarme **P1 CRÍTICA** do compressor, com 3 consequências agrupadas (↳) em P4. Na tela A, o trip se perde entre as linhas. |
| 3 | Clique em **Reconhecer** no alarme crítico. | O estado muda para *ATIVO · RECONHECIDO*. O alarme continua na lista, porque a condição persiste, e a ação aparece no registro do operador. |
| 4 | Continue a reprodução até cerca de 95 s. | O sensor TT-105 perde o sinal. A tela B mostra **SINAL RUIM** e um alarme de instrumento; a tela A exibe 0,0 sem aviso. |
| 5 | Clique em **↺ Reiniciar** para repetir. | O cenário volta ao início e se repete de forma idêntica. |

Outros controles: **+1 passo** avança meio segundo; o seletor de velocidade (1×, 2×, 5×)
ajusta a reprodução; **Só A** e **Só B** exibem uma tela por vez.

### Problemas comuns

| Sintoma | Solução |
|---|---|
| *"Python não foi encontrado"* | Reinstale o Python marcando *Add to PATH*, ou desative o alias `python` em *Configurações → Aplicativos → Aliases de execução do aplicativo*. |
| Porta 8000 ocupada | Use outra porta: `set PORTA_IHM=8080` (cmd) ou `$env:PORTA_IHM=8080` (PowerShell), e então execute `python servidor_ihm.py`. |

---

## Metodologia

### Cadeia de processamento

Cada amostra de sensor passa por cinco etapas, nesta ordem:

| Etapa | Função | Regra |
|---|---|---|
| 0. Qualidade do sinal | Detectar instrumento em falha. | Sinal ruim gera alarme de instrumento, em vez de ser descartado. |
| 1. Anti-ruído | Eliminar oscilações no limite. | Atraso de ativação de 1,5 s e banda morta de 2 % da faixa (alarmes HI e LO). |
| 2. Contexto | Inibir alarmes esperados no modo de operação. | Partida, parada e manutenção. Alarmes críticos nunca são inibidos; toda inibição é registrada. |
| 3. Deduplicação | Evitar linhas repetidas. | Repetição em até 8 s reabre a mesma linha e incrementa um contador. |
| 4. Correlação | Destacar a causa-raiz. | Sintomas de uma causa ativa são agrupados e rebaixados para P4. |

### Prioridades

| Nível | Símbolo | Critério |
|---|---|---|
| P1 · Crítica | ◆ | Risco à segurança. |
| P2 · Alta | ▲ | Alto impacto operacional. |
| P3 · Média | ■ | Impacto moderado, incluindo falha de instrumento. |
| P4 · Baixa | ● | Baixa relevância ou sintoma de causa já anunciada. |

A prioridade é codificada por cor **e** forma, para não depender apenas da percepção de cor.

### Ciclo de vida do alarme

Reconhecer um alarme registra quem tomou ciência e quando, mas **não o resolve**. O alarme
só deixa a lista quando o processo volta ao normal e o alarme já foi reconhecido. Os estados são
*ativo não reconhecido*, *ativo reconhecido* e *normalizado aguardando reconhecimento*.

### Princípios de IHM aplicados

- Fundo neutro, com cor reservada a condições anormais.
- Ordenação por relevância: não reconhecidos primeiro, depois prioridade e horário.
- Ação recomendada em cada alarme.
- Transparência do filtro: contadores de tudo o que foi agrupado, rebaixado ou inibido.

---

## Arquitetura

```
cenario_compressor.py → automacao.py → servidor_ihm.py → ihm/index.html
     (simulação)          (motor)       (HTTP/JSON)        (interface)
```

Toda a lógica fica no Python; o navegador apenas exibe o estado e envia as ações do operador.

| Arquivo | Responsabilidade |
|---|---|
| `codigo/automacao.py` | Motor de alarmes: filtros, priorização, correlação e ciclo de vida. |
| `codigo/cenario_compressor.py` | Cenário simulado determinístico (semente 42) e comparativo A × B. |
| `codigo/servidor_ihm.py` | Servidor HTTP local na porta 8000. |
| `codigo/ihm/index.html` | Interface do operador. |
| `codigo/test_automacao.py` | 18 testes automatizados. |

---

## Resultados

Cenário simulado de 150 s com 6 sensores e 301 amostras por sensor.

| Indicador | Tela A (sem motor) | Tela B (com motor) |
|---|---|---|
| Notificações totais | 109 | 5 |
| Geradas por ruído (V-201) | 101 | 0 |
| Trip do compressor | 5 (repetidas) | 1 (P1) |
| Consequências do trip | 3, sem hierarquia | 3, agrupadas em P4 |
| Avisos de sensor em falha | 0 | 1 |

Para reproduzir: `python cenario_compressor.py` (na pasta `codigo`).

---

## Evolução em relação à P1

Os defeitos abaixo foram reproduzidos por testes antes da correção. Executados contra o código
da P1, 12 dos 18 testes falham.

| Defeito na P1 | Correção na P2 |
|---|---|
| Alarmes nunca saíam da lista. | Ciclo de vida com normalização. |
| O primeiro alarme era suprimido quando o relógio iniciava em 0 s. | Deduplicação corrigida; repetições reabrem a mesma linha. |
| O modo manutenção inibia alarmes críticos. | Críticos nunca são inibidos. |
| Sinal de qualidade ruim era descartado sem aviso. | Gera alarme de instrumento. |
| Sintoma anterior à causa-raiz não era rebaixado. | Correlação reavaliada para todos os alarmes ativos. |
| Não havia reconhecimento pelo operador. | Reconhecimento com registro. |
| Scripts `.bat` apontavam para um arquivo inexistente. | Caminhos corrigidos. |

Também foram acrescentados a IHM comparativa, o cenário simulado e a suíte de testes.

---

## Testes

```bash
cd codigo
python -m unittest -v test_automacao.py
```

Os testes cobrem anti-ruído, ciclo de vida, deduplicação, inibição contextual, qualidade de
sinal, correlação, ordenação da lista e a demonstração original da P1. No Windows, o atalho
`executar_testes.bat` roda os testes e o comparativo.

---

## Limitações e trabalhos futuros

**Limitações:** dados simulados; grafo causal e regras de contexto definidos manualmente; um
único operador, sem autenticação nem persistência.

**Trabalhos futuros:** arquivamento temporário (*shelving*), alarme sonoro, histórico em banco
de dados com indicadores de desempenho, integração com OPC UA ou MQTT e testes de
usabilidade com operadores.

---

## Referências

- ANSI/ISA-18.2-2016. *Management of Alarm Systems for the Process Industries.*
- IEC 62682:2022. *Management of alarm systems for the process industries.*
- ANSI/ISA-101.01-2015. *Human Machine Interfaces for Process Automation Systems.*
- EEMUA. *Publication 191: Alarm Systems — A Guide to Design, Management and Procurement.*
- HOLLIFIELD, B.; HABIBI, E. *The Alarm Management Handbook.* 2. ed. Houston: PAS, 2010.

---

## Equipe

| Integrante | Atribuição |
|---|---|
| Bruno Silveira | Desenvolvimento do motor, da IHM e documentação |
