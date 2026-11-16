"""
Coupa — Aprovação de Requisições por Limite de Valor.

Abre a fila de requisições com aprovação pendente (com os filtros escolhidos —
por padrão: solicitante SGM e aprovador atual), aprova as que estão ABAIXO do limite e
deixa as demais para análise manual. No fim gera um relatório em Excel.

  Primeiro uso (login manual):   python main.py --login
  Uso normal:                    python main.py
  Só simular (não aprova nada):  python main.py --simular
  Limpar cache (mantém login):   python main.py --clear-cache

Também é o "motor" do aplicativo (app_aprovacoes.py), que chama
executar() e fazer_login() diretamente.
"""

import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().with_name(".env"))
except ImportError:
    pass


# ============================================================================
# CONFIGURAÇÕES (o .env, se existir, tem prioridade; o aplicativo passa as dele)
# ============================================================================
COUPA_URL = os.getenv("COUPA_URL") or "https://sua-empresa.coupahost.com/user/home"
LIMITE_VALOR = float(os.getenv("LIMITE_VALOR", "10000"))

# ---------- Filtros da fila (busca Avançada de Requisições) ----------
# Cada filtro: campo (valor interno do Coupa), rótulo (como aparece na tela),
# tipo "texto" (com condição + texto) ou "lista" (escolhe um valor da lista),
# condição e valor. O padrão é o mesmo da macro original.
# Para acrescentar campos novos, basta incluir em CAMPOS_DISPONIVEIS.
CAMPOS_DISPONIVEIS = {
    "requested_by": {"rotulo": "Solicitado por", "tipo": "texto"},
    "status": {"rotulo": "Status", "tipo": "lista",
               "opcoes": {"pending_approval": "Aprovação pendente"}},
    "current_approver_association.fullname": {"rotulo": "Nome do aprovador atual", "curto": "Aprovador",
                                              "tipo": "texto"},
}
CONDICOES = {"con": "contém"}

FILTROS_PADRAO = [
    {"campo": "requested_by", "condicao": "con", "valor": os.getenv("FILTRO_SOLICITANTE", "")},
    {"campo": "status", "valor": "pending_approval"},
    {"campo": "current_approver_association.fullname", "condicao": "con",
     "valor": os.getenv("APROVADOR", "")},
]
# Filtros que não podem sair: sem eles a automação poderia mexer em requisições
# fora da fila de aprovação ou de outros solicitantes.
CAMPOS_OBRIGATORIOS = ("requested_by", "status")


def descrever_filtro(f: dict) -> str:
    """{'campo': 'requested_by', 'condicao': 'con', 'valor': 'SGM'} -> 'Solicitado por contém “SGM”'"""
    info = CAMPOS_DISPONIVEIS.get(f["campo"], {"rotulo": f["campo"], "tipo": "texto"})
    if info["tipo"] == "lista":
        return f"{info['rotulo']}: {info.get('opcoes', {}).get(f['valor'], f['valor'])}"
    return f"{info['rotulo']} {CONDICOES.get(f.get('condicao', 'con'), f.get('condicao'))} “{f['valor']}”"


def descrever_curto(f: dict) -> str:
    """Versão curta para a tela: 'Solicitado por: SGM' | 'Aprovador: Fulano de Tal'."""
    info = CAMPOS_DISPONIVEIS.get(f["campo"], {"rotulo": f["campo"], "tipo": "texto"})
    valor = info.get("opcoes", {}).get(f["valor"], f["valor"])
    return f"{info.get('curto', info['rotulo'])}: {valor}"


def validar_filtros(filtros: list) -> list:
    """Devolve a lista de problemas (vazia = filtros ok)."""
    problemas = []
    campos = [f["campo"] for f in filtros]
    for obrigatorio in CAMPOS_OBRIGATORIOS:
        if obrigatorio not in campos:
            problemas.append(f"O filtro “{CAMPOS_DISPONIVEIS[obrigatorio]['rotulo']}” é obrigatório")
    if any(campos.count(c) > 1 for c in set(campos)):
        problemas.append("Há um campo repetido nos filtros")
    for f in filtros:
        if not str(f.get("valor", "")).strip():
            problemas.append(f"Preencha o valor de “{CAMPOS_DISPONIVEIS.get(f['campo'], {}).get('rotulo', f['campo'])}”")
    return problemas

PASTA_DADOS = Path(os.getenv("APROVACOES_DADOS")
                   or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CoupaAprovacoes" / "dados")
USER_DATA_DIR = PASTA_DADOS / "perfil_navegador"
RESULTADOS_DIR = PASTA_DADOS / "resultados"
ERROS_DIR = PASTA_DADOS / "erros"
PASTA_DEBUG = PASTA_DADOS / "debug_requisicoes"

# Segurança contra loop infinito de paginação (na prática não passa disso)
MAX_PAGINAS = 50
# Depois de processar, a fila é lida de novo para pegar o que entrou nesse meio tempo
MAX_RODADAS = 5


class SessaoExpirada(Exception):
    pass


def notificar_no_terminal(evento, **d):
    if evento == "item_fim":
        marcas = {"aprovada": "✅ aprovada", "seria_aprovada": "✅ seria aprovada (simulação)",
                  "acima": "⏭️  acima do limite", "sem_botao": "⏭️  sem botão de aprovação",
                  "erro": "❌ erro"}
        valor = f" — R$ {formatar_brl(d['valor'])}" if d.get("valor") is not None else ""
        print(f"  {marcas[d['resultado']]}{valor}" + (f": {d['motivo']}" if d.get("motivo") else ""))
    elif evento == "item_inicio":
        print(f"\n[{d['n']}/{d['total']}] Requisição {d['req']}")
    elif evento == "aviso":
        print(f"⚠️  {d['texto']}")


# ============================================================================
# VALORES
# ============================================================================
def formatar_brl(valor: float) -> str:
    """10000.5 -> '10.000,50'"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parsear_valor(texto: str) -> float:
    """
    Converte o texto de valor do Coupa em número. Aceita:
    '1.234,56' | 'R$ 1.234,56' | '1.234,56 BRL' | '1,234.56' | '1234' | '-1.234,56'
    """
    t = str(texto).replace("\xa0", " ")
    t = re.sub(r"[^\d,.\-]", "", t)
    if not re.search(r"\d", t):
        raise ValueError(f"valor ilegível: '{texto}'")
    negativo = t.startswith("-")
    t = t.lstrip("-")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):          # 1.234,56 (Brasil)
            t = t.replace(".", "").replace(",", ".")
        else:                                     # 1,234.56 (EUA)
            t = t.replace(",", "")
    elif "," in t:
        inteiro, _, dec = t.rpartition(",")
        t = (inteiro.replace(",", "") + "." + dec) if len(dec) <= 2 else t.replace(",", "")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", t):
        t = t.replace(".", "")                    # 1.234.567 ou 1.234 (milhar)
    valor = float(t)
    return -valor if negativo else valor


def ler_valor_total(page) -> tuple:
    """
    Soma o valor de TODAS as linhas da requisição. A versão anterior lia só a
    primeira linha: uma requisição com várias linhas podia ser aprovada mesmo
    com o total acima do limite. Somar nunca dá menos que o total real.
    Devolve (valor_total, quantidade_de_linhas).
    """
    locator = page.locator(".priceInfo .lineTotal")
    locator.first.wait_for(timeout=10_000)
    textos = [t for t in locator.all_inner_texts() if t.strip()]
    if not textos:
        raise ValueError("valor da requisição não encontrado na tela")
    return sum(parsear_valor(t) for t in textos), len(textos)


# ============================================================================
# NAVEGAÇÃO E FILTROS (mesma lógica da versão anterior)
# ============================================================================
def base_coupa(url: str) -> str:
    m = re.match(r"(https?://[^/]+)", url.strip())
    return m.group(1) if m else url.rstrip("/")


def sessao_expirou(page) -> bool:
    url = page.url.lower()
    return "login" in url or "sessions" in url or "microsoftonline" in url or "saml" in url


def navegar_para_requisicoes(page, url: str) -> None:
    print("Abrindo o Coupa...")
    page.goto(url, wait_until="load")
    if sessao_expirou(page):
        raise SessaoExpirada()
    print("Abrindo Requisições...")
    try:
        page.click("img[alt='Requests / Procurement']", timeout=10_000)
    except Exception:
        page.click("a[href*='requisition']", timeout=10_000)
    page.wait_for_load_state("load")


def aplicar_filtros(page, filtros: list) -> None:
    """
    Monta a busca Avançada com os filtros (todas as condições) e pesquisa.
    Só mexe no que está diferente do desejado, para não recarregar a lista à toa.
    Na tela do Coupa, os filtros de TEXTO têm condição + caixa de texto; os de
    LISTA têm uma lista de valores. Cada tipo é contado separadamente, como na
    macro original.
    """
    filtro_principal = page.locator("select#requisition_header_filter")
    if filtro_principal.evaluate("el => el.value") != "13":
        print("Selecionando 'Todos' no filtro principal...")
        filtro_principal.select_option(value="13")
        page.wait_for_load_state("load")

    if not page.locator("[data-cond-col-select='true']").first.is_visible():
        print("Abrindo painel Avançado...")
        try:
            page.locator("a:has(span:text-is('Avançado'))").first.click(timeout=5_000)
        except Exception:
            page.locator("span:text-is('Avançado')").first.click(timeout=5_000, force=True)
        page.wait_for_timeout(2_000)

    cond_op = page.locator("select#cond_op_requisition_header")
    if cond_op.count() > 0 and cond_op.evaluate("el => el.value") != "all":
        cond_op.select_option(value="all", force=True)
        page.wait_for_timeout(300)

    colunas = page.locator("[data-cond-col-select='true']")
    n_texto = n_lista = 0
    for i, f in enumerate(filtros):
        info = CAMPOS_DISPONIVEIS.get(f["campo"], {"tipo": "texto"})
        print(f"Filtro {i + 1}: {descrever_filtro(f)}")
        if colunas.count() < i + 1:
            page.locator("img.sprite-add[title*='grupo 1']").first.click()
            page.wait_for_timeout(1_500)
        if colunas.nth(i).evaluate("el => el.value") != f["campo"]:
            colunas.nth(i).select_option(value=f["campo"], force=True)
            page.wait_for_timeout(3_000)          # o Coupa recarrega as condições via AJAX

        if info["tipo"] == "lista":
            lista = page.locator("select[aria-label='Filtrar valor']").nth(n_lista)
            marcados = page.evaluate("el => Array.from(el.selectedOptions).map(o => o.value)",
                                     lista.element_handle())
            if f["valor"] not in marcados:
                lista.select_option(value=f["valor"], force=True)
                page.wait_for_timeout(300)
            n_lista += 1
        else:
            condicao = page.locator("select.cond_comparator").nth(n_texto)
            if condicao.evaluate("el => el.value") != f.get("condicao", "con"):
                condicao.select_option(value=f.get("condicao", "con"), force=True)
                page.wait_for_timeout(300)
            texto = page.locator("input[aria-label='Filtrar texto']").nth(n_texto)
            if texto.evaluate("el => el.value") != f["valor"]:
                texto.fill(f["valor"], force=True)
            n_texto += 1

    if colunas.count() > len(filtros):
        print(f"⚠️  O Coupa tem {colunas.count()} filtros na tela e só {len(filtros)} foram configurados — "
              "confira a busca Avançada se a lista parecer estranha.")

    print("Pesquisando...")
    fingerprint = primeiro_id_da_tabela(page)
    page.click("#search_advanced_button_requisition_header")
    esperar_tabela_mudar(page, fingerprint, "após a busca")
    print("Filtros aplicados — lista carregada.")


# ============================================================================
# LEITURA DA LISTA (todas as páginas)
# ============================================================================
def _spans_da_tabela(page):
    """IDs de requisição só dentro da tabela de resultados (evita pegar links de outras partes da tela)."""
    container = page.locator("#requisition_header_table, table.list, #content")
    if container.count() > 0:
        return container.first.locator("span.dt_open_link")
    return page.locator("span.dt_open_link")


def primeiro_id_da_tabela(page):
    spans = page.locator("span.dt_open_link")
    return spans.first.inner_text() if spans.count() > 0 else None


def esperar_tabela_mudar(page, fingerprint_antes, contexto: str) -> None:
    """
    Espera a tabela REALMENTE atualizar (o 1º ID muda ou a lista fica vazia),
    em vez de confiar só no evento "load", que dispara antes do AJAX terminar —
    a causa provável de ler requisições antigas/cacheadas.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    page.wait_for_load_state("load")
    try:
        page.wait_for_function(
            """(fpAntes) => {
                const spans = document.querySelectorAll('span.dt_open_link');
                if (spans.length === 0) return true;
                if (!fpAntes) return true;
                return spans[0].innerText.trim() !== fpAntes.trim();
            }""",
            arg=fingerprint_antes,
            timeout=15_000,
        )
    except PlaywrightTimeoutError:
        print(f"  ⚠️  Não detectei mudança na tabela {contexto} — seguindo mesmo assim.")
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)


def ir_para_proxima_pagina(page) -> bool:
    """Clica em "Avançar" (rodapé da tabela). False = já estava na última página."""
    proximo = page.locator("a.next_page.requisition_header_wait")
    if proximo.count() == 0:
        proximo = page.locator("a:has-text('Avançar')")
    if proximo.count() == 0:
        return False
    fingerprint = primeiro_id_da_tabela(page)
    print("  ➡️  Avançando para a próxima página...")
    proximo.first.click()
    esperar_tabela_mudar(page, fingerprint, "após avançar")
    return True


def coletar_ids_todas_paginas(page) -> list:
    """Percorre todas as páginas (clicando em "Avançar") e junta os IDs."""
    todos, pagina = [], 1
    while True:
        ids = coletar_ids_requisicoes(page)
        print(f"  Página {pagina}: {len(ids)} requisição(ões).")
        todos.extend(i for i in ids if i not in todos)
        if pagina >= MAX_PAGINAS:
            print(f"  ⚠️  Limite de segurança de {MAX_PAGINAS} páginas atingido — parando por precaução.")
            break
        if not ir_para_proxima_pagina(page):
            break
        pagina += 1
    print(f"Total na fila: {len(todos)} requisição(ões) em {pagina} página(s).")
    return todos


def coletar_ids_requisicoes(page) -> list:
    spans = _spans_da_tabela(page)
    ids = []
    for texto in spans.all_inner_texts():
        texto = texto.strip()
        if texto.isdigit() and texto not in ids:
            ids.append(texto)
    return ids


# ============================================================================
# APROVAÇÃO DE UMA REQUISIÇÃO
# ============================================================================
def _texto_de_todos_os_frames(page) -> str:
    """Texto do frame principal + iframes (o Coupa mostra o fluxo de aprovadores em iframe)."""
    pedacos = []
    for frame in page.frames:
        try:
            texto = frame.locator("body").inner_text(timeout=2_000)
            if texto:
                pedacos.append(texto)
        except Exception:
            continue
    return "\n".join(pedacos)


def conferir_requisicao(page, req_id: str, filtros: list) -> str:
    """
    Confere na página da própria requisição se os textos dos filtros (solicitante,
    aprovador...) aparecem. É só um AVISO — não bloqueia a aprovação, porque a
    leitura por texto/iframe pode dar falso negativo. Devolve o aviso ('' se ok).
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)
    try:
        texto = _texto_de_todos_os_frames(page)
    except Exception as erro:
        return f"não consegui ler a página para conferir ({erro})"
    normalizado = " ".join(texto.split()).lower()
    faltando = [f["valor"] for f in filtros
                if CAMPOS_DISPONIVEIS.get(f["campo"], {}).get("tipo") == "texto"
                and " ".join(str(f["valor"]).split()).lower() not in normalizado]
    if not faltando:
        return ""
    try:
        PASTA_DEBUG.mkdir(parents=True, exist_ok=True)
        (PASTA_DEBUG / f"{req_id}.txt").write_text(texto, encoding="utf-8")
    except Exception:
        pass
    aviso = "não achei na página: " + ", ".join(f"“{v}”" for v in faltando)
    print(f"  ⚠️  {aviso} (texto salvo em {PASTA_DEBUG / (req_id + '.txt')})")
    return aviso


def processar_uma(page, url: str, req_id: str, limite: float, simular: bool, filtros: list = ()) -> dict:
    page.goto(f"{base_coupa(url)}/approver/{req_id}/edit", wait_until="load")
    if sessao_expirou(page):
        raise SessaoExpirada()
    aviso = conferir_requisicao(page, req_id, filtros) if filtros else ""

    botao_aprovar = page.locator("span:text-is('Aprovar')").first
    try:
        botao_aprovar.wait_for(timeout=3_000)
    except Exception:
        return {"resultado": "sem_botao", "valor": None,
                "motivo": "; ".join(m for m in ("Sem botão de aprovação para você", aviso) if m)}

    valor, linhas = ler_valor_total(page)
    motivo = "; ".join(m for m in (f"{linhas} linhas somadas" if linhas > 1 else "", aviso) if m)

    if valor >= limite:
        return {"resultado": "acima", "valor": valor, "motivo": motivo}
    if simular:
        return {"resultado": "seria_aprovada", "valor": valor, "motivo": motivo}

    url_antes = page.url
    botao_aprovar.click()
    page.wait_for_load_state("load")
    # Confirma a aprovação: a página sai da requisição (o Coupa pode até abrir a
    # próxima pendente) OU o botão Aprovar some. Se nada disso acontecer em 10s,
    # registra para conferência em vez de contar como aprovada.
    limite_espera = time.time() + 10
    while time.time() < limite_espera:
        if page.url != url_antes or f"/{req_id}/" not in page.url:
            break
        try:
            if not page.locator("span:text-is('Aprovar')").first.is_visible():
                break
        except Exception:
            break
        page.wait_for_timeout(300)
    else:
        return {"resultado": "erro", "valor": valor,
                "motivo": "Cliquei em Aprovar, mas o Coupa não confirmou — confira esta requisição"}
    page.wait_for_timeout(500)
    return {"resultado": "aprovada", "valor": valor, "motivo": motivo}


def motivo_amigavel(erro) -> str:
    if isinstance(erro, SessaoExpirada):
        return "A sessão do Coupa expirou — faça o login de novo"
    texto = str(erro)
    if "lineTotal" in texto and "Timeout" in texto:
        return "O valor da requisição não apareceu na tela a tempo"
    if "Timeout" in texto:
        return "O Coupa demorou demais para responder"
    if "has been closed" in texto:
        return "O navegador foi fechado durante a execução"
    return texto.strip().split("\n")[0][:200]


# ============================================================================
# RELATÓRIO
# ============================================================================
NOMES_RESULTADO = {"aprovada": "Aprovada", "seria_aprovada": "Seria aprovada (simulação)",
                   "acima": "Acima do limite — análise manual", "sem_botao": "Sem botão de aprovação",
                   "erro": "Erro — não aprovada"}
CORES_RESULTADO = {"aprovada": "C6EFCE", "seria_aprovada": "DDEBF7", "acima": "FFEB9C",
                   "sem_botao": "E7EBF0", "erro": "FFC7CE"}


def gerar_relatorio(resultados, url: str, limite: float, simular: bool, filtros: list = ()) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Aprovações"
    titulo = f"Aprovações Coupa — {datetime.now():%d/%m/%Y %H:%M} — limite R$ {formatar_brl(limite)}"
    if simular:
        titulo += " — SIMULAÇÃO (nada foi aprovado)"
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(["Filtros: " + "  ·  ".join(descrever_filtro(f) for f in filtros)])
    ws["A2"].font = Font(italic=True, color="6B7280")
    ws.append(["Requisição", "Valor (R$)", "Resultado", "Observação", "Link"])
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F6FEB")
    for r in resultados:
        link = f"{base_coupa(url)}/requisition_headers/{r['req']}"
        ws.append([int(r["req"]), r["valor"], NOMES_RESULTADO[r["resultado"]], r["motivo"], link])
        linha = ws[ws.max_row]
        for c in linha:
            c.fill = PatternFill("solid", fgColor=CORES_RESULTADO[r["resultado"]])
        linha[1].number_format = '#,##0.00'
        linha[4].hyperlink = link
        linha[4].font = Font(color="2259C7", underline="single")
        linha[3].alignment = Alignment(wrap_text=True, vertical="top")
    for col, larg in zip("ABCDE", (12, 14, 32, 50, 60)):
        ws.column_dimensions[col].width = larg
    ws.freeze_panes = "A4"

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = RESULTADOS_DIR / f"aprovacoes_{datetime.now():%Y%m%d_%H%M%S}{'_simulacao' if simular else ''}.xlsx"
    wb.save(caminho)
    return caminho


# ============================================================================
# NAVEGADOR E EXECUÇÃO
# ============================================================================
def abrir_navegador(p, discreto: bool = False):
    """
    discreto=True (execuções automáticas): a janela abre fora da área visível,
    para não roubar a tela de quem está usando o computador. Não é "headless":
    é o mesmo Edge de sempre, com o mesmo login.
    """
    for pasta in (USER_DATA_DIR, RESULTADOS_DIR, ERROS_DIR):
        pasta.mkdir(parents=True, exist_ok=True)
    args = ["--window-position=-32000,-32000", "--window-size=1600,1000"] if discreto else ["--start-maximized"]
    # Não deixa o Edge "economizar" quando a janela está escondida ou a tela
    # bloqueada (ele desacelera páginas em segundo plano e a automação ficaria lenta).
    args += ["--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
             "--disable-renderer-backgrounding"]
    try:
        return p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR), channel="msedge", headless=False,
            no_viewport=not discreto, viewport={"width": 1600, "height": 1000} if discreto else None,
            args=args)
    except Exception as erro:
        if "already in use" in str(erro).lower() or "lock" in str(erro).lower():
            raise RuntimeError("O navegador da automação já está aberto em outra janela — "
                               "feche-o e tente de novo.")
        raise


def limpar_cache_navegador() -> list:
    """Limpa o cache do Edge da automação sem perder o login (cookies ficam)."""
    pasta = USER_DATA_DIR / "Default"
    removidos = []
    if not pasta.exists():
        return removidos
    for item in ("Cache", "Code Cache", "GPUCache", "Service Worker", "Local Storage",
                 "Session Storage", "IndexedDB", "Network"):
        alvo = pasta / item
        if alvo.exists():
            shutil.rmtree(alvo, ignore_errors=True)
            removidos.append(item)
    return removidos


def fazer_login(url: str = None, esperar_confirmacao=None) -> None:
    from playwright.sync_api import sync_playwright
    url = url or COUPA_URL
    esperar_confirmacao = esperar_confirmacao or (lambda: input(
        "\nDepois de logar, volte aqui e aperte Enter para salvar a sessão..."))
    with sync_playwright() as p:
        context = abrir_navegador(p)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        print(">>> Faça o login no Coupa na janela do navegador.")
        esperar_confirmacao()
        context.close()


def executar(url: str = None, limite: float = None, filtros: list = None,
             simular: bool = False, notificar=notificar_no_terminal, parar=None, discreto: bool = False) -> dict:
    """
    Processa a fila. `parar` (threading.Event) interrompe ENTRE uma requisição e outra.
    """
    from playwright.sync_api import sync_playwright
    url = (url or COUPA_URL).strip()
    limite = LIMITE_VALOR if limite is None else limite
    filtros = filtros or FILTROS_PADRAO
    if not url:
        raise RuntimeError("Endereço do Coupa não configurado")
    problemas = validar_filtros(filtros)
    if problemas:
        raise RuntimeError("Filtros inválidos: " + "; ".join(problemas))

    resultados, vistos = [], set()
    interrompido = sessao_caiu = False

    with sync_playwright() as p:
        context = abrir_navegador(p, discreto)
        page = context.pages[0] if context.pages else context.new_page()
        for aba in list(context.pages[1:]):
            try:
                aba.close()
            except Exception:
                pass
        try:
            for rodada in range(1, MAX_RODADAS + 1):
                navegar_para_requisicoes(page, url)
                aplicar_filtros(page, filtros)
                # "90 por página" fica DESLIGADO: o clique automático não teve o mesmo
                # efeito do manual. A paginação por "Avançar" cobre a fila inteira.
                novos = [i for i in coletar_ids_todas_paginas(page) if i not in vistos]
                if not novos:
                    break
                vistos.update(novos)
                total = len(vistos)
                notificar("lista", total=total, rodada=rodada, novos=len(novos))
                print(f"{len(novos)} requisição(ões) nova(s) na lista (total até agora: {total}).")

                for req_id in novos:
                    if parar is not None and parar.is_set():
                        interrompido = True
                        break
                    n = len(resultados) + 1
                    notificar("item_inicio", n=n, total=total, req=req_id)
                    try:
                        r = processar_uma(page, url, req_id, limite, simular, filtros)
                    except SessaoExpirada:
                        sessao_caiu = True
                        break
                    except Exception as erro:
                        print(f"  Erro: {str(erro).splitlines()[0][:200]}")
                        r = {"resultado": "erro", "valor": None, "motivo": motivo_amigavel(erro)}
                        try:
                            page.screenshot(path=str(ERROS_DIR / f"erro_{req_id}.png"))
                        except Exception:
                            pass
                    resultados.append({"req": req_id, **r})
                    notificar("item_fim", n=n, total=total, req=req_id, **r)
                if interrompido or sessao_caiu:
                    break
                if simular:
                    break        # na simulação nada sai da fila: uma passada basta
        except SessaoExpirada:
            sessao_caiu = True
        try:
            page.goto(url, wait_until="load")
        except Exception:
            pass
        context.close()

    if sessao_caiu:
        notificar("aviso", texto="A sessão do Coupa expirou — faça o login de novo e rode outra vez.")
    contagem = {k: sum(1 for r in resultados if r["resultado"] == k) for k in NOMES_RESULTADO}
    relatorio = gerar_relatorio(resultados, url, limite, simular, filtros) if resultados else None
    total_aprovado = sum(r["valor"] or 0 for r in resultados if r["resultado"] in ("aprovada", "seria_aprovada"))

    print("\n" + "=" * 52)
    print(f"  {'Seriam aprovadas' if simular else 'Aprovadas'}: "
          f"{contagem['aprovada'] + contagem['seria_aprovada']} (R$ {formatar_brl(total_aprovado)})")
    print(f"  Acima do limite (R$ {formatar_brl(limite)}): {contagem['acima']}")
    print(f"  Sem botão de aprovação: {contagem['sem_botao']}")
    print(f"  Erros: {contagem['erro']}")
    if relatorio:
        print(f"  Relatório: {relatorio}")
    print("=" * 52)
    return {"contagem": contagem, "relatorio": relatorio, "interrompido": interrompido,
            "sessao_expirada": sessao_caiu, "total_aprovado": total_aprovado, "simular": simular}


def main() -> None:
    if "--clear-cache" in sys.argv:
        removidos = limpar_cache_navegador()
        print("Cache limpo: " + (", ".join(removidos) if removidos else "nada para limpar") + " (login mantido).")
        if "--login" not in sys.argv:
            return
    if "--login" in sys.argv:
        fazer_login()
        return
    executar(simular="--simular" in sys.argv)


if __name__ == "__main__":
    main()
