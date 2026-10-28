# Coupa — Aprovação de Requisições por Limite de Valor

Script em Python + Playwright que abre a fila de requisições com aprovação pendente no Coupa, aprova as que estão abaixo de um limite de valor e deixa as demais para análise manual.

Uso no meu trabalho, no back-office de Manutenção, para as requisições abertas pelo sistema de chamados que ficam aguardando a minha aprovação.

---

## Por que existe

Essas requisições chegam em volume e a conferência é sempre a mesma: abrir, ler o valor, aprovar, voltar para a lista. O script faz essa parte repetitiva, mas **só aprova o que está abaixo do limite**. Todo o resto continua passando por uma pessoa.

---

## O que o script faz

1. Abre o Coupa (com a sessão já salva) e vai até a lista de requisições
2. Monta a busca avançada com três filtros combinados (todas as condições):
   - **Solicitado por** contém o valor de `FILTRO_SOLICITANTE`
   - **Status** = Aprovação pendente
   - **Nome do aprovador atual** contém o valor de `APROVADOR` (opcional)
   - Antes de mexer em cada filtro, confere se ele já está certo, para não recarregar a lista à toa
3. Para cada requisição da lista:
   - Abre a tela de aprovação; se não houver botão **Aprovar**, pula
   - Lê o valor e converte do formato brasileiro (`1.234,56`)
   - **Abaixo do limite** → aprova
   - **Igual ou acima** → não toca, só registra
   - **Qualquer erro** (valor ilegível, tela que não carregou) → não aprova e registra o motivo
4. Mostra no terminal o resumo: aprovadas, pendentes e erros, com número e valor de cada uma

---

## Exemplo de saída

```
====================================================
📋  RELATÓRIO FINAL
====================================================
  Total processado : 5
  ✅ Aprovadas      : 3
  ⏭️  Pendentes      : 1  (valor >= R$ 10,000.00)
  ❌ Erros          : 1

  Aprovadas:
    • 300001  →  R$ 1,250.00
    • 300002  →  R$ 3,980.50
    • 300003  →  R$ 820.00

  Pendentes (acima do limite):
    • 300004  →  R$ 15,400.00
====================================================
```
*(números fictícios)*

---

## Instalação

Requisitos: Python 3.10+ e Microsoft Edge.

```bash
git clone https://github.com/Neres73/Coupa_aprovacoes.git
cd Coupa_aprovacoes

python -m venv .venv
.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
playwright install msedge
```

## Configuração

Copie o modelo e preencha com os dados do seu ambiente:

```bash
copy .env.example .env            # Linux/Mac: cp .env.example .env
```

| Variável | O que é | Padrão |
|---|---|---|
| `COUPA_URL` | Página inicial do seu Coupa | obrigatória |
| `LIMITE_VALOR` | Requisições abaixo deste valor são aprovadas | `10000` |
| `FILTRO_SOLICITANTE` | Texto buscado em "Solicitado por" | `SGM` |
| `APROVADOR` | Texto buscado em "Nome do aprovador atual" | vazio (filtro não é usado) |
| `USER_DATA_DIR` | Pasta do perfil do navegador com a sessão | `./perfil_navegador` |

O `.env` e a pasta do perfil estão no `.gitignore` e nunca vão para o repositório.

## Uso

```bash
python main.py --login    # 1ª vez: abre o Edge para você fazer login; a sessão fica salva
python main.py            # execuções seguintes
```

O script **não lê, guarda nem digita senha**. Se a sessão expirar, é só rodar `--login` de novo.

---

## Limitações

- Os seletores são da interface do Coupa em português no ambiente onde o script foi feito; outro ambiente pode exigir ajustes
- O resumo sai só no terminal (não gera arquivo)
- Um limite único para todas as requisições; não há regra por categoria ou centro de custo
- Sem modo de simulação: rodar o script **aprova de verdade** o que estiver abaixo do limite

## Estrutura

```
├── main.py            # filtros, leitura do valor, regra de aprovação e resumo
├── requirements.txt
├── .env.example       # modelo de configuração
└── .gitignore
```

---

Desenvolvido por [Gustavo Neres](https://github.com/Neres73), com apoio do Claude (IA) para modelar a lógica, escrever e revisar o código. Projeto compartilhado como portfólio: nenhuma URL, credencial ou dado da empresa está no repositório. Licença MIT.
