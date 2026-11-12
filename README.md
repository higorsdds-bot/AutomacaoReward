# Automação Microsoft Rewards — Dashboard Windows Forms

Automação desktop em Python para o **Microsoft Rewards** com painel visual estilo **Windows Forms (`Tkinter/TTK`)**, simulação de comportamento humano via **Microsoft Edge nativo (CDP)**, **Identificador de Tarefas** inteligente e relatórios detalhados de diagnóstico em tempo real.

---

## ✨ Funcionalidades Principais

- **Dashboard Desktop (Estilo Windows Forms):**
  - Cartões de indicadores em tempo real (`Status Atual`, `Pesquisas Computadas`, `Cards / Atividades (7s)` e `Erros / Falhas`).
  - Botão de início rápido (`▶ INICIAR AUTOMAÇÃO`), parada segura (`⏹ Parar Execução`) e exportação do relatório completo para `.CSV`.
  - Tabela de diagnóstico detalhando o motivo exato de cada sucesso, aviso ou falha.
- **Identificador de Tarefas Inteligente:**
  - Escaneia as abas **Painel de Controle (`/dashboard`)** e **Ganhar (`/earn`)** antes de clicar em qualquer card.
  - Identifica automaticamente tarefas já marcadas como **`Concluído`** e **não repete** atividades já finalizadas no dia.
  - Verifica se a missão em etapas **"Veja o seu novo dashboard" (+95)** ainda está disponível antes de abri-la (evitando avisos de *"Esta oferta não está disponível para você"*).
  - Consulta o **Detalhamento de pontos** (`Pesquisa do Bing X/15`) e pula automaticamente as pesquisas de teclado quando a cota diária já foi atingida.
- **Simulação de Fluxo Humano (Anti-Detecção):**
  - Controle nativo do **Microsoft Edge** via protocolo CDP (`SimpleWebSocketCDP`), utilizando apenas a biblioteca padrão do Python (zero dependências externas).
  - Movimentação física de mouse, eventos nativos de teclado (`windowsVirtualKeyCode`), digitação de **espaço no final** de cada termo pesquisado (`" "`), permanência configurável de **7 segundos** na página aberta e intervalo de **10 segundos** entre pesquisas.
  - Retorno automático de páginas explicativas (`/about?section=benefits`) para nunca travar fora do fluxo de missões.

---

## 📁 Estrutura do Projeto

| Arquivo | Descrição |
| :--- | :--- |
| `app.py` | Interface gráfica Desktop (Dashboard Windows Forms) com controles de tempo, KPIs e tabela de relatórios. |
| `automation.py` | Motor de automação CDP para o Microsoft Edge: login automático, Identificador de Tarefas, execução de missões e pesquisas no Bing. |
| `search_terms.py` | Gerador dinâmico de termos de pesquisa variados em português e mapeador contextual para cards de missão. |
| `iniciar_painel.bat` | Atalho para abrir o painel diretamente com duplo clique no Windows. |
| `requirements.txt` | Informativo de ambiente (usa 100% biblioteca padrão do Python 3.10+). |

---

## 🚀 Como Executar

### 1. Pré-requisitos
- **Windows 10 ou 11** com **Microsoft Edge** instalado.
- **Python 3.10+** instalado.

### 2. Iniciando o Painel
Basta dar dois cliques no arquivo **`iniciar_painel.bat`** ou executar no terminal:

```bash
python app.py
```

### 3. Configurando e Rodando
1. No painel lateral esquerdo, confira o **E-mail** e a **Senha** da sua conta Microsoft.
2. Ajuste os tempos humanos conforme desejar (padrão recomendado):
   - **Permanência na página:** `7.0s`
   - **Intervalo entre pesquisas:** `10.0s`
   - **Velocidade de digitação:** `85ms` por tecla
3. Clique em **`▶ INICIAR AUTOMAÇÃO`**.
4. Acompanhe cada etapa na tabela **Relatório de Execução e Diagnóstico de Falhas**.

