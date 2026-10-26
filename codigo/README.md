# Gestão de Alarmes Industriais — versão P2 (COM8 · IUM/IHM)

Motor de processamento de alarmes em Python (sem dependências externas) e uma
**IHM de demonstração antes/depois ligada ao motor**. Projeto acadêmico: os dados
são **simulados** (compressor fictício C-101); nada aqui foi validado em planta
real, e o projeto **não declara conformidade** com a ISA-18.2, a IEC 62682 ou a ISA-101.
Essas normas são usadas como referência conceitual.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `automacao.py` | Motor de alarmes (antigo `automacao.py.py`, renomeado). Mantém a demonstração da P1. |
| `test_automacao.py` | 18 testes `unittest`, incluindo testes de regressão dos defeitos da P1. |
| `cenario_compressor.py` | Cenário simulado (semente fixa) e comparativo A × B. |
| `servidor_ihm.py` + `ihm/index.html` | IHM no navegador; cada clique chama o motor Python. |
| `executar_testes.bat` / `executar_ihm.bat` | Atalhos para o Windows. |
| `.vscode/launch.json` | Configurações de execução no VS Code. |

## Como executar no Windows

1. Instale o Python 3.9 ou superior (python.org), marcando **"Add python.exe to PATH"**.
2. Descompacte a pasta `codigo`.
3. **Pelo Explorador:** clique duas vezes em `executar_testes.bat` (testes e comparativo)
   ou em `executar_ihm.bat` (abre a IHM em `http://localhost:8000`).
4. **Pelo VS Code:** *Arquivo → Abrir pasta…* → `codigo`; instale a extensão *Python*
   (Microsoft); vá em *Executar e Depurar* (Ctrl+Shift+D) e escolha uma das configurações.
5. **Pelo terminal** (na pasta `codigo`):
   ```
   python -m unittest -v test_automacao.py
   python cenario_compressor.py
   python servidor_ihm.py
   ```

### Roteiro da demonstração em sala
1. Abra a IHM, mostre **A + B** e clique em **▶ Reproduzir** (2×).
2. Durante o ruído inicial, a lista A cresce sem parar (nível do V-201 oscila em
   torno de 75 %); a tela B continua vazia (filtro on-delay + banda morta).
3. Clique em **⏭ Ir para o trip**: em B aparece 1 alarme **P1 CRÍTICA** com 3
   consequências agrupadas e rebaixadas para P4; em A o trip se perde entre as linhas.
4. Clique em **Reconhecer** na linha crítica: o estado muda para
   *ATIVO · RECONHECIDO* (a condição continua) e a ação vai para o registro do operador.
5. Continue: o TT-105 perde sinal. B mostra **SINAL RUIM** e um alarme de instrumento;
   A continua exibindo um valor “normal” (0,0), sem nenhum aviso.

## O que mudou da P1 para a P2 (defeitos reproduzidos por teste)

| Nº | Defeito na P1 | Correção |
|---|---|---|
| 5 | O alarme nunca saía da lista (o código de normalização estava inalcançável). | Ciclo de vida com normalização. |
| 6 | A deduplicação suprimia o 1º alarme quando o relógio começava em 0 s. | Usa "sem histórico" em vez de 0.0; repetição reabre a mesma linha com contador. |
| 7 | O modo MAINTENANCE (`*`) suprimia até alarmes críticos. | Críticos nunca são inibidos; toda inibição é registrada. |
| 8 | O sinal com qualidade ruim era descartado em silêncio. | Gera um alarme de instrumento ("valor não confiável"). |
| 9 | O sintoma que chegava antes da causa-raiz não era rebaixado. | Correlação reavaliada para todos os ativos. |
| 10 | Não existia reconhecimento. | `acknowledge()`: reconhecer **não** resolve; há registro do operador. |
| — | O `.bat` e o `launch.json` apontavam para `codigo-gerado.py.py`, que não existe. | Corrigidos. |

Rodando os mesmos 18 testes contra o código da P1, 12 falham (4 falhas de
asserção, nos defeitos 6 a 9, e 8 erros por funcionalidade inexistente).

## Resultado da simulação (reproduzível: `python cenario_compressor.py`)

Mesmas 301 amostras por sensor (150 s simulados, 6 sensores):

* **Cenário A (sem racionalização):** 109 notificações, sendo 101 do nível do V-201
  (ruído) e 5 do próprio trip oscilando no limite; **0 avisos** sobre o sensor em falha.
* **Cenário B (motor):** 5 anunciações, sendo 1 crítica, 3 sintomas agrupados sob a
  causa-raiz (rebaixados para P4) e 1 alarme de instrumento.

São números de **uma simulação didática construída pelo grupo**, não uma medição de planta.

## Limitações conhecidas
* Grafo causal e regras de contexto escritos à mão (não aprendidos de dados).
* Latências da demonstração da P1 incluem um acréscimo fixo simulado.
* Sem *shelving*, sem som e sem persistência em banco de dados (propostas futuras).
* Um único operador e um único console; sem autenticação.
