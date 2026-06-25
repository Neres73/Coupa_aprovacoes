"""
Coupa - Aprovação de Requisições
Filtra requisições SGM exigindo aprovação e aprova as abaixo de R$10.000.

  Primeiro uso (login manual):   python main.py --login
  Uso normal (já logado):        python main.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

COUPA_URL     = "https://gpabr.coupahost.com/user/home"
LIMITE_VALOR  = 10_000.00
USER_DATA_DIR = Path("./perfil_navegador").resolve()
USER_DATA_DIR.mkdir(exist_ok=True, parents=True)


# ============================================================================
# LOGIN MANUAL (modo --login)
# ============================================================================
def fazer_login_manual(context: BrowserContext) -> None:
    page = context.new_page()
    page.goto(COUPA_URL)
    print("\n>>> Faça login no Coupa nessa janela do Edge.")
    input("\nDepois de logar, volte aqui e aperte Enter para salvar a sessão...")
    print("Sessão salva em:", USER_DATA_DIR)


# ============================================================================
# ETAPA 1 — Navegar para requisições e aplicar filtros SGM
# ============================================================================
def navegar_para_requisicoes(page: Page) -> None:
    """Abre o Coupa e vai até a página de requisições. Roda só uma vez."""
    print("Abrindo Coupa...")
    page.goto(COUPA_URL, wait_until="load")

    print("Clicando em Requisições / Procurement...")
    try:
        page.click("img[alt='Requests / Procurement']", timeout=10_000)
    except PlaywrightTimeoutError:
        page.click("a[href*='requisition']", timeout=10_000)
    page.wait_for_load_state("load")


def aplicar_filtros_sgm(page: Page) -> None:
    """Aplica os 3 filtros na página de requisições já aberta.
    Verifica o estado atual antes de alterar — não reconfigura o que já está certo."""

    # ── Dropdown principal: selecionar "Todos" ───────────────────────────
    filtro_principal = page.locator("select#requisition_header_filter")
    if filtro_principal.evaluate("el => el.value") != "13":
        print("Selecionando 'Todos' no filtro principal...")
        filtro_principal.select_option(value="13")
        page.wait_for_load_state("load")

    # ── Painel Avançado: abre se ainda estiver fechado ───────────────────
    painel_aberto = page.locator("[data-cond-col-select='true']").first.is_visible()
    if not painel_aberto:
        print("Abrindo painel Avançado...")
        try:
            page.locator("a:has(span:text-is('Avançado'))").first.click(timeout=5_000)
        except PlaywrightTimeoutError:
            page.locator("span:text-is('Avançado')").first.click(timeout=5_000, force=True)
        page.wait_for_timeout(2_000)

    # ── AND: todas as condições devem ser atendidas ──────────────────────
    cond_op = page.locator("select#cond_op_requisition_header")
    if cond_op.count() > 0 and cond_op.evaluate("el => el.value") != "all":
        print("Definindo 'Corresponder TODAS as condições' (AND)...")
        cond_op.select_option(value="all", force=True)
        page.wait_for_timeout(300)

    filtros = page.locator("[data-cond-col-select='true']")

    # ════════════════════════════════════════════════════════════════════
    # FILTRO 1 — Solicitado por | contém | SGM
    # ════════════════════════════════════════════════════════════════════
    print("Verificando filtro 1 (Solicitado por)...")
    if filtros.nth(0).evaluate("el => el.value") != "requested_by":
        filtros.nth(0).select_option(value="requested_by", force=True)
        page.wait_for_timeout(3_000)

    op1 = page.locator("select.cond_comparator").nth(0)
    if op1.evaluate("el => el.value") != "con":
        op1.select_option(value="con", force=True)
        page.wait_for_timeout(300)

    txt1 = page.locator("input[aria-label='Filtrar texto']").nth(0)
    if txt1.evaluate("el => el.value") != "SGM":
        txt1.fill("SGM", force=True)

    # ════════════════════════════════════════════════════════════════════
    # FILTRO 2 — Status | Aprovação pendente
    # ════════════════════════════════════════════════════════════════════
    print("Verificando filtro 2 (Status)...")
    if filtros.count() < 2:
        print("  Adicionando novo filtro...")
        page.locator("img.sprite-add[title*='grupo 1']").first.click()
        page.wait_for_timeout(1_500)

    if filtros.nth(1).evaluate("el => el.value") != "status":
        filtros.nth(1).select_option(value="status", force=True)
        page.wait_for_timeout(2_000)

    # Status é um select múltiplo — verifica se pending_approval já está selecionado
    status_sel = page.locator("select[aria-label='Filtrar valor']").first
    valores_status = page.evaluate("el => Array.from(el.selectedOptions).map(o => o.value)",
                                   status_sel.element_handle())
    if "pending_approval" not in valores_status:
        status_sel.select_option(value="pending_approval", force=True)
        page.wait_for_timeout(300)

    # ════════════════════════════════════════════════════════════════════
    # FILTRO 3 — Nome do aprovador atual | contém | Carlos Henrique
    # ════════════════════════════════════════════════════════════════════
    print("Verificando filtro 3 (Nome do aprovador atual)...")
    if filtros.count() < 3:
        print("  Adicionando novo filtro...")
        page.locator("img.sprite-add[title*='grupo 1']").first.click()
        page.wait_for_timeout(1_500)

    if filtros.nth(2).evaluate("el => el.value") != "current_approver_association.fullname":
        filtros.nth(2).select_option(value="current_approver_association.fullname", force=True)
        page.wait_for_timeout(3_000)  # aguarda AJAX atualizar o operador

    op3 = page.locator("select.cond_comparator").nth(1)
    if op3.evaluate("el => el.value") != "con":
        op3.select_option(value="con", force=True)
        page.wait_for_timeout(300)

    txt3 = page.locator("input[aria-label='Filtrar texto']").nth(1)
    if txt3.evaluate("el => el.value") != "Carlos Henrique":
        txt3.fill("Carlos Henrique", force=True)

    # ── Pesquisar ────────────────────────────────────────────────────────
    print("Clicando em Pesquisar...")
    page.click("#search_advanced_button_requisition_header")
    page.wait_for_load_state("load")
    print("✅ Filtros aplicados — lista carregada.")




# ============================================================================
# ETAPA 2 — Processar cada requisição
# ============================================================================
def parsear_valor_brl(texto: str) -> float:
    limpo = texto.strip().replace(".", "").replace(",", ".")
    return float(limpo)


def coletar_ids_requisicoes(page: Page) -> list[str]:
    spans = page.locator("span.dt_open_link")
    ids = []
    for i in range(spans.count()):
        texto = spans.nth(i).inner_text().strip()
        if texto.isdigit():
            ids.append(texto)
    print(f"  {len(ids)} requisição(ões) encontrada(s) na lista.")
    return ids


def processar_requisicoes(page: Page) -> None:
    ids = coletar_ids_requisicoes(page)
    aprovadas = []
    puladas   = []
    erros     = []

    if not ids:
        print("Nenhuma requisição SGM encontrada na fila de aprovação.")
    else:
        for req_id in ids:
            url_req = f"https://gpabr.coupahost.com/approver/{req_id}/edit"
            print(f"\nProcessando requisição {req_id}...")

            try:
                page.goto(url_req, wait_until="load")

                # ── Verificar se botão Aprovar existe (3s) ───────────────
                botao_aprovar = page.locator("span:text-is('Aprovar')").first
                try:
                    botao_aprovar.wait_for(timeout=3_000)
                except PlaywrightTimeoutError:
                    print(f"  ⏭️  Sem botão de aprovação — pulando.")
                    puladas.append((req_id, 0))
                    continue

                # ── Ler o valor total ────────────────────────────────────
                locator_valor = page.locator(".priceInfo .lineTotal").first
                locator_valor.wait_for(timeout=10_000)
                valor = parsear_valor_brl(locator_valor.inner_text().strip())
                print(f"  Valor: R$ {valor:,.2f}")

                if valor >= LIMITE_VALOR:
                    print(f"  ⏭️  Acima do limite — pendente.")
                    puladas.append((req_id, valor))
                    continue

                # ── Aprovar ──────────────────────────────────────────────
                botao_aprovar.click()
                page.wait_for_load_state("load")
                page.wait_for_timeout(1_000)
                print(f"  ✅ Aprovada.")
                aprovadas.append((req_id, valor))

            except Exception as e:
                print(f"  ❌ Erro: {e}")
                erros.append((req_id, str(e)))

    # ── Relatório final ───────────────────────────────────────────────────
    total = len(aprovadas) + len(puladas) + len(erros)
    print("\n" + "=" * 52)
    print("📋  RELATÓRIO FINAL")
    print("=" * 52)
    print(f"  Total processado : {total}")
    print(f"  ✅ Aprovadas      : {len(aprovadas)}")
    print(f"  ⏭️  Pendentes      : {len(puladas)}  (valor >= R$ {LIMITE_VALOR:,.2f})")
    print(f"  ❌ Erros          : {len(erros)}")

    if aprovadas:
        print("\n  Aprovadas:")
        for req_id, valor in aprovadas:
            print(f"    • {req_id}  →  R$ {valor:,.2f}")

    if puladas:
        print("\n  Pendentes (acima do limite):")
        for req_id, valor in puladas:
            print(f"    • {req_id}  →  R$ {valor:,.2f}" if valor > 0 else f"    • {req_id}  →  sem botão de aprovação")

    if erros:
        print("\n  Erros:")
        for req_id, motivo in erros:
            print(f"    • {req_id}  →  {motivo}")

    print("=" * 52)

    print("Voltando à tela inicial do Coupa...")
    page.goto(COUPA_URL, wait_until="load")


# ============================================================================
# EXECUÇÃO PRINCIPAL
# ============================================================================
def main() -> None:
    modo_login = "--login" in sys.argv

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            channel="msedge",
            headless=False,
        )

        if modo_login:
            fazer_login_manual(context)
            context.close()
            return

        # Mantém a primeira aba, fecha as extras
        if context.pages:
            page = context.pages[0]
            for aba in list(context.pages[1:]):
                try:
                    aba.close()
                except Exception:
                    pass
        else:
            page = context.new_page()

        navegar_para_requisicoes(page)   # abre Coupa e vai até a página (só uma vez)
        aplicar_filtros_sgm(page)        # aplica filtros SGM
        processar_requisicoes(page)

        input("\nPressione ENTER para fechar o browser...")
        context.close()


if __name__ == "__main__":
    main()
