# Coupa — Aprovação Automatizada de Requisições

Automação em Python + Playwright que percorre a fila de requisições com aprovação pendente em um portal Coupa, aplica a regra de alçada configurada e aprova apenas o que está dentro do limite — registrando tudo em um relatório auditável.

> Processo antes executado manualmente, requisição a requisição, passou a ser concluído em segundos por lote, sem intervenção humana.

---

## Contexto

Em um fluxo de compras corporativo, requisições de baixo valor de um mesmo solicitante se acumulam aguardando aprovação manual. A conferência é repetitiva (abrir, ler valor, aprovar, voltar), mas não é trivial: aprovar algo acima da alçada gera compromisso financeiro indevido.

A automação resolve a parte repetitiva **sem abrir mão do controle**: tudo acima do limite é deliberadamente ignorado e reportado para decisão humana.

---

## Como funciona

1. Abre o portal e navega até a listagem de requisições
2. Aplica três filtros combinados por `AND`:
   - Solicitante contém o identificador configurado
   - Status igual a "Aprovação pendente"
   - Aprovador atual contém o nome configurado
3. Para cada requisição da fila:
   - Verifica se a ação de aprovar está disponível
   - Lê e converte o valor total
   - Abaixo do limite → aprova
   - Igual ou acima do limite → registra como pendente e segue adiante
4. Emite o relatório final (aprovadas, pendentes, erros)
5. Retorna à tela inicial

---

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.10+ |
| Automação de navegador | Playwright (contexto persistente) |
| Configuração | Variáveis de ambiente (`python-dotenv`) |

---

## Instalação

```bash
git clone https://github.com/Neres73/Coupa_aprovacoes.git
cd Coupa_aprovacoes

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install msedge
```

---

## Configuração

Toda a configuração é feita por variáveis de ambiente — **nenhum dado de ambiente corporativo fica versionado**.

Copie o modelo e preencha com os valores do seu ambiente:

```bash
cp .env.example .env
```

```env
COUPA_URL=https://seu-ambiente.coupahost.com/user/home
LIMITE_VALOR=10000.00
FILTRO_SOLICITANTE=PREFIXO
FILTRO_APROVADOR=Nome do Aprovador
USER_DATA_DIR=./perfil_navegador
```

| Variável | Descrição | Padrão |
|---|---|---|
| `COUPA_URL` | URL base do ambiente Coupa | — (obrigatória) |
| `LIMITE_VALOR` | Alçada máxima para aprovação automática | `10000.00` |
| `FILTRO_SOLICITANTE` | Texto buscado no campo "Solicitado por" | — (obrigatória) |
| `FILTRO_APROVADOR` | Texto buscado no campo "Aprovador atual" | — (obrigatória) |
| `USER_DATA_DIR` | Pasta do perfil de navegador com a sessão salva | `./perfil_navegador` |

---

## Uso

### Primeira execução — autenticação

```bash
python main.py --login
```

Abre o navegador para login manual. A sessão fica persistida em `USER_DATA_DIR` e é reaproveitada nas execuções seguintes — a automação **nunca manipula credenciais**.

### Execução normal

```bash
python main.py
```

### Simulação (recomendado antes de rodar em volume)

```bash
python main.py --dry-run
```

Percorre a fila e monta o relatório sem executar nenhuma aprovação.

---

## Relatório

```
====================================================
  RELATORIO FINAL
====================================================
  Total processado : 5
  Aprovadas        : 3
  Pendentes        : 1  (valor >= limite configurado)
  Erros            : 1

  Aprovadas:
    • 3068XX  →  R$ 5.998,00
    • 3071XX  →  R$ 3.200,00
    • 3072XX  →  R$ 8.750,00

  Pendentes (acima do limite):
    • 3075XX  →  R$ 15.000,00
====================================================
```

---

## Decisões técnicas

- **Contexto persistente do Playwright** em vez de automatizar o login: credenciais nunca passam pelo código, e a sessão sobrevive entre execuções.
- **Fail-safe no limite de alçada**: qualquer falha na leitura ou conversão do valor faz a requisição ser tratada como pendente, nunca como aprovável. O erro seguro é não aprovar.
- **Filtros verificados antes de aplicados**: o estado atual do formulário é lido e só reescrito se estiver divergente, evitando recarregamentos desnecessários da listagem.
- **Relatório por execução**: cada corrida devolve o que foi aprovado, o que foi deixado para decisão humana e o que falhou — rastreabilidade mínima para um processo que movimenta valor.
- **Erros isolados por item**: uma falha em uma requisição não interrompe o lote.

---

## Limitações e próximos passos

- Depende da estrutura de DOM do portal — mudanças de layout exigem ajuste dos seletores
- Sem suíte de testes automatizados; o `--dry-run` cobre a validação manual hoje
- Relatório apenas em terminal — exportação para CSV/log persistente é a próxima evolução
- Alçada única; regras por centro de custo ou categoria ainda não são suportadas

---

## Estrutura

```
.
├── main.py            # fluxo principal: filtros, iteração e regra de alçada
├── requirements.txt
├── .env.example       # modelo de configuração
├── .gitignore         # ignora .env e o perfil de navegador
└── README.md
```

---

## Licença

MIT — ver [LICENSE](LICENSE).

---

Projeto pessoal desenvolvido a partir de uma necessidade real de trabalho. Nenhuma URL, credencial ou dado de ambiente corporativo está versionado neste repositório.
