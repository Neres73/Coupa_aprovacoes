# Coupa — Aprovação de Requisições

Automação com Python e Playwright que filtra requisições SGM com aprovação pendente no Coupa e aprova automaticamente as que possuem valor abaixo de R$ 10.000,00.

---

## O que faz

1. Abre o Coupa e navega até a página de Requisições
2. Aplica três filtros combinados com **todas as condições** (AND):
   - **Solicitado por** contém `SGM`
   - **Status** igual a `Aprovação pendente`
   - **Nome do aprovador atual** contém `Carlos Henrique`
3. Para cada requisição encontrada:
   - Verifica se o botão "Aprovar" está disponível
   - Lê o valor total da requisição
   - Se **abaixo de R$ 10.000** → aprova
   - Se **acima de R$ 10.000** → registra como pendente e pula
4. Exibe relatório final com aprovadas, pendentes e erros
5. Retorna à tela inicial do Coupa

---

## Pré-requisitos

- Python 3.10+
- Microsoft Edge instalado
- PyCharm (recomendado)

### Instalação das dependências

```bash
pip install playwright
playwright install msedge
```

---

## Configuração

Abra o arquivo `main.py` e ajuste as variáveis no topo conforme o seu ambiente:

```python
COUPA_URL     = "https://gpabr.coupahost.com/user/home"  # URL do Coupa
LIMITE_VALOR  = 10_000.00                                 # Limite para aprovação
USER_DATA_DIR = Path("./perfil_navegador")                # Pasta do perfil do Edge
```

Se quiser alterar o nome do aprovador filtrado, localize esta linha em `aplicar_filtros_sgm`:

```python
if txt3.evaluate("el => el.value") != "Carlos Henrique":
    txt3.fill("Carlos Henrique", force=True)
```

---

## Como usar

### Primeiro uso — salvar o login

Execute uma vez para salvar a sessão do Coupa:

```bash
python main.py --login
```

Uma janela do Edge abrirá. Faça o login normalmente e pressione **Enter** no terminal. A sessão ficará salva na pasta `perfil_navegador/` e não precisará ser repetida.

### Uso normal

```bash
python main.py
```

A automação roda sozinha e exibe o relatório no terminal ao finalizar.

---

## Relatório final

Ao término, o terminal exibirá um resumo como:

```
====================================================
📋  RELATÓRIO FINAL
====================================================
  Total processado : 5
  ✅ Aprovadas      : 3
  ⏭️  Pendentes      : 1  (valor >= R$ 10.000,00)
  ❌ Erros          : 1

  Aprovadas:
    • 306810  →  R$ 5.998,00
    • 307144  →  R$ 3.200,00
    • 307201  →  R$ 8.750,00

  Pendentes (acima do limite):
    • 307500  →  R$ 15.000,00
====================================================
```

---

## Observações

- O perfil salvo em `perfil_navegador/` mantém a sessão ativa entre execuções — **não apague essa pasta**
- Se a sessão expirar, rode novamente com `--login`
- Nunca rode duas automações simultaneamente usando o mesmo `perfil_navegador/`
- Os filtros são verificados antes de serem aplicados — se já estiverem corretos, não são reconfigurados
