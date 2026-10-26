# Gestão de Alarmes Industriais — Compressor C-101

> **Menos alarmes, mais decisão.**
> Projeto P2 da disciplina **COM8 · IUM/IHM**: motor de gestão de alarmes em Python e uma
> IHM de alto desempenho para um compressor industrial **fictício** (C-101).

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependências](https://img.shields.io/badge/depend%C3%AAncias-nenhuma-brightgreen)
![Testes](https://img.shields.io/badge/testes-18%20passando-brightgreen)
![Status](https://img.shields.io/badge/status-acad%C3%AAmico-lightgrey)

---

## Sumário

1. [Sobre a entrega da P2](#1-sobre-a-entrega-da-p2)
2. [Contexto e problema de negócio](#2-contexto-e-problema-de-negócio)
3. [Objetivos](#3-objetivos)
4. [Solução proposta](#4-solução-proposta)
5. [Arquitetura](#5-arquitetura)
6. [A interface (IHM)](#6-a-interface-ihm)
7. [O que mudou da P1 para a P2](#7-o-que-mudou-da-p1-para-a-p2)
8. [Resultados da simulação](#8-resultados-da-simulação)
9. [Como executar](#9-como-executar)
10. [Roteiro da apresentação](#10-roteiro-da-apresentação)
11. [Qualidade e testes](#11-qualidade-e-testes)
12. [Limitações e trabalhos futuros](#12-limitações-e-trabalhos-futuros)
13. [Referências](#13-referências)
14. [Equipe](#14-equipe)

---

## 1. Sobre a entrega da P2

A P2 parte dos trabalhos entregues na P1, **com os mesmos grupos e o mesmo tema**. Ficou definido que:

| # | Exigência da disciplina | Como este repositório atende |
|---|---|---|
| 1 | O trabalho escrito pode ser complementado em uma nova versão. | Este README é a **versão complementada** do texto da P1: registra o que foi corrigido, o que foi acrescentado (IHM, ciclo de vida, testes) e os resultados. |
| 2 | Deve ser preparada uma apresentação (slides). | [`Gestão de Alarmes – Compressor C-101.pptx`](./Gestão%20de%20Alarmes%20–%20Compressor%20C-101.pptx), com 9 slides, e uma IHM funcionando para a demonstração ao vivo. |
| 3 | Slides e texto complementar entregues até **23/10, às 19h**, mesma data do início das apresentações. | Slides + este README + código em [`codigo/`](./codigo). |

**Tema do grupo:** gestão de alarmes industriais e IHM de alto desempenho para um compressor de gás.

---

## 2. Contexto e problema de negócio

> *Quando tudo alarma, nada alarma.*

Em salas de controle industriais, um sistema de alarmes mal configurado transforma cada desvio
em um aviso. O resultado conhecido é a **inundação de alarmes**:

| Problema | O que acontece | Impacto para o negócio |
|---|---|---|
| **Inundação** | A lista cresce mais rápido do que o operador consegue ler. | Carga cognitiva alta, fadiga, alarmes ignorados. |
| **Ruído (*chattering*)** | Um sinal oscilando em torno do limite gera dezenas de linhas iguais que não pedem ação. | O operador aprende a reconhecer sem ler. |
| **Causa-raiz escondida** | Um evento (ex.: trip do compressor) dispara vários alarmes-consequência com a mesma prioridade. | Diagnóstico lento e reação tardia. |
| **Falha silenciosa de instrumento** | Um sensor com defeito mostra um valor "normal" (0,0) sem aviso. | Decisões tomadas sobre dado falso. |

O custo de um alarme crítico perdido no meio do ruído é parada não programada, dano a
equipamento e, no pior caso, um acidente.

### Personas

| Persona | Necessidade | Como a solução responde |
|---|---|---|
| **Operador de painel** | Ver primeiro o que exige ação e saber o que fazer. | Lista ordenada por estado e prioridade, com ação recomendada em cada linha. |
| **Supervisor de turno** | Saber quem reconheceu o quê, e quando. | Registro do operador com horário e resultado. |
| **Engenheiro de automação** | Confiar que o filtro não esconde nada importante. | Contadores de tudo o que foi agrupado, rebaixado ou inibido; críticos nunca são inibidos. |

---

## 3. Objetivos

**Geral:** reduzir o número de notificações apresentadas ao operador sem perder nenhuma informação
relevante para a segurança, e apresentá-las numa IHM que guie o olhar para o que importa.

**Específicos:**

- Filtrar ruído com atraso de ativação (*on-delay*) e banda morta (histerese).
- Agrupar sintomas sob a causa-raiz e rebaixar sua prioridade.
- Implementar o ciclo de vida do alarme, em que **reconhecer não resolve**.
- Transformar falha de sinal em alarme de instrumento, em vez de silêncio.
- Nunca inibir alarmes críticos, nem em modo de manutenção.
- Demonstrar o ganho com um comparativo **antes × depois** sobre os mesmos dados.

### Indicadores de sucesso (no cenário simulado)

| Indicador | Meta | Resultado |
|---|---|---|
| Redução de notificações | ≥ 90 % | **95,4 %** (109 → 5) |
| Alarmes críticos perdidos | 0 | **0** |
| Falhas de instrumento sinalizadas | 100 % | **1 de 1** |
| Testes automatizados passando | 100 % | **18 de 18** |

---

## 4. Solução proposta

O motor (`AlarmProcessor`) processa cada amostra de sensor por uma **cadeia de filtros em cascata**:

```
 sinal de campo
      │
      ▼
 ┌─────────────────┐  qualidade ruim? ──► alarme de INSTRUMENTO ("valor não confiável")
 │ 0. Qualidade    │
 └────────┬────────┘
          ▼
 ┌─────────────────┐  oscilação curta no limite ──► descartada
 │ 1. Anti-ruído   │  (on-delay 1,5 s + banda morta 2 % da faixa, HI ou LO)
 └────────┬────────┘
          ▼
 ┌─────────────────┐  alarme esperado no modo atual ──► inibido e REGISTRADO
 │ 2. Contexto     │  (partida, parada, manutenção) — CRÍTICO nunca é inibido
 └────────┬────────┘
          ▼
 ┌─────────────────┐  repetição em até 8 s ──► reabre a MESMA linha (+1 no contador)
 │ 3. Deduplicação │
 └────────┬────────┘
          ▼
 ┌─────────────────┐  sintoma de uma causa ativa ──► agrupado e rebaixado para P4
 │ 4. Correlação   │  (reavaliada para todos os ativos, inclusive retroativamente)
 └────────┬────────┘
          ▼
    anunciação na IHM
```

### Prioridades

| Nível | Símbolo | Uso |
|---|---|---|
| **P1 · Crítica** | ◆ | Risco à segurança (ex.: trip do compressor). |
| **P2 · Alta** | ▲ | Alto impacto operacional. |
| **P3 · Média** | ■ | Impacto moderado; inclui falhas de instrumento. |
| **P4 · Baixa** | ● | Baixa relevância ou sintoma de uma causa já anunciada. |

A prioridade é indicada por **cor e forma**, para não depender só da cor (daltonismo).

### Ciclo de vida do alarme

```
                 operador reconhece
 ATIVO, NÃO  ───────────────────────►  ATIVO, RECONHECIDO
 RECONHECIDO                           (condição continua)
     │                                         │
     │ processo normaliza                      │ processo normaliza
     ▼                                         ▼
 NORMALIZADO, AGUARDA  ──────────────►  SAI DA LISTA
 RECONHECIMENTO        operador          (fica no histórico de eventos)
                       reconhece
```

Reconhecer registra **quem** tomou ciência e **quando**. O alarme só sai da lista quando o processo
volta ao normal *e* o operador já reconheceu.

---

## 5. Arquitetura

Quatro peças e um único caminho de dados. **O navegador não decide nada**: cada clique chama o motor Python.

```
 cenario_compressor.py ──► automacao.py ──► servidor_ihm.py ──► ihm/index.html
   (simulação, 6 sensores,   (motor de        (HTTP + JSON em      (desenha o estado e
    150 s, semente 42)        alarmes)         localhost:8000)      envia os cliques)
                                 ▲
                         test_automacao.py
                         (18 testes unittest)
```

| Arquivo | Responsabilidade |
|---|---|
| [`codigo/automacao.py`](./codigo/automacao.py) | Motor de alarmes: filtros, priorização, correlação, ciclo de vida, métricas. Mantém a demonstração da P1. |
| [`codigo/cenario_compressor.py`](./codigo/cenario_compressor.py) | Cenário simulado determinístico e comparativo A × B. |
| [`codigo/servidor_ihm.py`](./codigo/servidor_ihm.py) | Servidor HTTP com a API `GET /api/estado`, `POST /api/avancar`, `POST /api/reconhecer`, `POST /api/reiniciar`. |
| [`codigo/ihm/index.html`](./codigo/ihm/index.html) | IHM no navegador (HTML/CSS/JS puro). |
| [`codigo/test_automacao.py`](./codigo/test_automacao.py) | 18 testes, incluindo regressão dos defeitos da P1. |
| `codigo/executar_*.bat` | Atalhos para Windows. |
| `codigo/.vscode/launch.json` | Configurações de execução no VS Code. |

**Decisões técnicas**

- **Zero dependências externas** — só a biblioteca padrão do Python 3.9+. Roda em qualquer máquina do laboratório.
- **Simulação determinística** (semente 42) — a demonstração e os números do relatório são sempre iguais.
- **Lógica só no backend** — a IHM é uma camada de apresentação; o comportamento testado é o mesmo que aparece na tela.

---

## 6. A interface (IHM)

A IHM mostra **a mesma planta em duas telas lado a lado**, alimentadas pelas mesmas amostras:

| | **Tela A — sem racionalização** | **Tela B — com o motor** |
|---|---|---|
| Notificações | Cada cruzamento do limite vira uma linha. | Só o que exige atenção. |
| Cores | Tudo pisca, tudo é vermelho. | Fundo neutro; cor reservada para o anormal. |
| Trip do compressor | Perdido entre dezenas de linhas. | 1 alarme P1 com os 3 sintomas agrupados (↳). |
| Sensor em falha | Mostra 0,0, sem aviso. | **SINAL RUIM** hachurado + alarme de instrumento. |
| Orientação | Nenhuma. | Ação recomendada e botão **Reconhecer** em cada linha. |

### Elementos da tela B

1. **Visão de processo** — seis cartões com valor, limite e prioridade; sensor em falha aparece hachurado.
2. **Lista de alarmes** — não reconhecidos primeiro, depois prioridade e horário; sintomas com ↳ sob a causa.
3. **Registro do operador** — quem reconheceu, quando e com que resultado.
4. **Transparência do filtro** — contadores de tudo o que foi agrupado, rebaixado ou inibido. Nada é apagado.

**Controles:** ▶ Reproduzir · +1 passo · ⏭ Ir para o trip · velocidade · A + B / Só A / Só B.

### Princípios de IHM aplicados (ISA-101 como referência)

- Fundo neutro em cinza; cor só para o que está anormal.
- Hierarquia visual: o que exige ação aparece primeiro e com mais destaque.
- Redundância de codificação (cor + forma + texto) para a prioridade.
- Informação acionável: cada alarme diz *o que fazer*, não só *o que aconteceu*.
- Transparência: o operador pode ver o que o filtro escondeu e por quê.

---

## 7. O que mudou da P1 para a P2

### Defeitos da P1 encontrados e corrigidos

Cada defeito foi primeiro **reproduzido por um teste** e só depois corrigido.

| Nº | Defeito na P1 | Correção na P2 |
|---|---|---|
| 5 | O alarme nunca saía da lista (código de normalização inalcançável). | Ciclo de vida completo com normalização. |
| 6 | A deduplicação suprimia o 1º alarme quando o relógio começava em 0 s. | "Sem histórico" deixa de ser tratado como 0,0; a repetição reabre a mesma linha com contador. |
| 7 | O modo MAINTENANCE (`*`) suprimia até alarmes críticos. | Críticos nunca são inibidos; toda inibição é registrada. |
| 8 | Sinal com qualidade ruim era descartado em silêncio. | Gera alarme de instrumento ("valor não confiável"). |
| 9 | Sintoma que chegava antes da causa-raiz não era rebaixado. | Correlação reavaliada para todos os ativos. |
| 10 | Não existia reconhecimento. | `acknowledge()`: reconhecer **não** resolve; há registro do operador. |
| — | `.bat` e `launch.json` apontavam para `codigo-gerado.py.py`, que não existe. | Caminhos corrigidos; `automacao.py.py` renomeado para `automacao.py`. |

Rodando os mesmos 18 testes contra o código da P1, **12 falham** (4 falhas de asserção nos
defeitos 6 a 9 e 8 erros por funcionalidade inexistente).

### Novidades da P2

- IHM de demonstração antes × depois, ligada ao motor real.
- Cenário simulado do compressor C-101 com roteiro de eventos.
- Campos voltados ao operador: ação recomendada, unidade, equipamento, contador de repetições, sintomas relacionados.
- Rastreabilidade: registro de eventos, de ações do operador e de supressões.
- Suíte de 18 testes automatizados.

---

## 8. Resultados da simulação

Cenário de **150 s**, **6 sensores**, **301 amostras por sensor**, semente fixa 42.

| Instante | Evento |
|---|---|
| 0 s | Operação normal; nível do vaso V-201 oscila em torno do limite (ruído). |
| 30 s | Pressão de descarga do C-101 começa a subir. |
| 62 s | Pressão passa de 85 bar de forma sustentada. |
| 75 s | **Trip** do compressor: vazão, pressão do coletor e temperatura do resfriador se desviam. |
| 95 s | Sensor TT-105 do mancal perde a qualidade de sinal. |
| 115 s | Sinal do TT-105 volta; pressão cai após o trip. |

| | Cenário A (sem racionalização) | Cenário B (com o motor) |
|---|---|---|
| **Notificações** | **109** | **5** |
| Ruído do V-201 | 101 | 0 |
| Trip oscilando no limite | 5 | 1 (P1 crítica) |
| Sintomas do trip | 3, com prioridade cheia | 3, agrupados e rebaixados para P4 |
| Aviso de sensor em falha | **0** | 1 alarme de instrumento |

**De 109 avisos para 5 decisões.**

> São números de uma **simulação didática construída pelo grupo**, não uma medição de planta.
> Para reproduzir: `python cenario_compressor.py`.

---

## 9. Como executar

**Pré-requisito:** Python 3.9 ou superior ([python.org](https://www.python.org/downloads/)).
No Windows, marque **"Add python.exe to PATH"** na instalação. Não há pacotes para instalar.

```bash
git clone https://github.com/BrunoSilveira100/gestao-de-alarmes-c101.git
cd gestao-de-alarmes-c101/codigo
```

| Objetivo | Comando |
|---|---|
| Abrir a IHM (`http://localhost:8000`) | `python servidor_ihm.py` |
| Rodar os testes | `python -m unittest -v test_automacao.py` |
| Ver o comparativo A × B | `python cenario_compressor.py` |
| Demonstração original da P1 | `python automacao.py` |

**Atalhos no Windows:** clique duas vezes em `codigo/executar_ihm.bat` ou `codigo/executar_testes.bat`.

**No VS Code:** *Arquivo → Abrir pasta…* → `codigo`, instale a extensão *Python* (Microsoft) e use
*Executar e Depurar* (Ctrl+Shift+D).

Para usar outra porta: defina a variável de ambiente `PORTA_IHM` (ex.: `PORTA_IHM=8080`).

---

## 10. Roteiro da apresentação

Slides: [`Gestão de Alarmes – Compressor C-101.pptx`](./Gestão%20de%20Alarmes%20–%20Compressor%20C-101.pptx)

| Slide | Conteúdo |
|---|---|
| 1 | Capa — *Menos alarmes, mais decisão* e escala de prioridades |
| 2 | O problema — inundação, ruído e risco |
| 3 | Referências — ISA-18.2 / IEC 62682 e ISA-101 (conceitos, não certificação) |
| 4 | Arquitetura — quatro peças, um caminho de dados |
| 5 | Ciclo de vida — reconhecer não resolve |
| 6 | O cenário simulado — 150 s do compressor C-101 |
| 7 | A interface — telas A e B lado a lado |
| 8 | Tela B em detalhe |
| 9 | Encerramento — de 109 avisos para 5 decisões |

### Demonstração ao vivo (≈ 3 min)

1. Abra a IHM em **A + B** e clique em **▶ Reproduzir** (2×).
2. Durante o ruído inicial, a lista A cresce sem parar; a tela B continua vazia (on-delay + banda morta).
3. Clique em **⏭ Ir para o trip**: em B aparece 1 alarme **P1 CRÍTICA** com 3 consequências agrupadas em P4; em A o trip se perde entre as linhas.
4. Clique em **Reconhecer** na linha crítica: o estado muda para *ATIVO · RECONHECIDO* (a condição continua) e a ação vai para o registro do operador.
5. Continue: o TT-105 perde sinal. B mostra **SINAL RUIM** e um alarme de instrumento; A segue exibindo 0,0, sem aviso.

---

## 11. Qualidade e testes

```bash
cd codigo
python -m unittest -v test_automacao.py
# Ran 18 tests ... OK
```

| Área | Testes |
|---|---|
| Anti-ruído | on-delay, histerese HI, histerese LO, direção inválida |
| Ciclo de vida | normalização após reconhecimento, normalizado sem reconhecimento, reconhecer não resolve |
| Deduplicação | 1º alarme com relógio em 0 s, condição ativa não duplica, repetição reabre a mesma linha |
| Contexto | crítico nunca suprimido em manutenção, supressão registrada |
| Qualidade de sinal | sinal ruim gera alarme de instrumento |
| Correlação | sintoma depois da causa, sintoma **antes** da causa (retroativo) |
| IHM / métricas | ordenação da lista, percentis de latência |
| Regressão | demonstração original da P1 continua passando |

Os testes com prefixo `P5`–`P9` reproduzem os defeitos da P1 e falham no código antigo.

---

## 12. Limitações e trabalhos futuros

**Limitações conhecidas**

- Grafo causal e regras de contexto escritos à mão, não aprendidos de dados.
- As latências da demonstração da P1 incluem um acréscimo fixo simulado (+12 ms / +45 ms).
- Um único operador e um único console, sem autenticação.
- Dados 100 % simulados; nada foi validado em planta real.

**Propostas para versões futuras**

- *Shelving* (arquivamento temporário com prazo) e alarme sonoro por prioridade.
- Persistência do histórico em banco de dados e relatórios de KPIs de alarmes (alarmes/hora por operador, top 10 ofensores).
- Integração com fontes reais via OPC UA ou MQTT (os sinais já são empacotados em `SensorSignal`).
- Testes de usabilidade com operadores (tempo para identificar a causa-raiz na tela A × tela B).

---

## 13. Referências

- ANSI/ISA-18.2-2016 — *Management of Alarm Systems for the Process Industries.*
- IEC 62682:2022 — *Management of alarm systems for the process industries.*
- ANSI/ISA-101.01-2015 — *Human Machine Interfaces for Process Automation Systems.*
- EEMUA Publication 191 — *Alarm Systems: A Guide to Design, Management and Procurement.*
- HOLLIFIELD, B.; HABIBI, E. *The Alarm Management Handbook.* PAS, 2010.

> **Aviso acadêmico:** as normas são usadas como **referência conceitual**. O projeto **não declara
> conformidade** com nenhuma delas. Tags, grafo causal e dados são fictícios.

---

## 14. Equipe

Disciplina **COM8 · IUM/IHM** — Projeto P2.

| Nome | Papel |
|---|---|
| Bruno Silveira | Desenvolvimento do motor, IHM e documentação |
| _(integrante)_ | _(papel)_ |
| _(integrante)_ | _(papel)_ |
