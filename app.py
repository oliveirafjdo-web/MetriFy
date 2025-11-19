
import os
import io
import sqlite3
from datetime import datetime

import pandas as pd
from flask import Flask, render_template, request, redirect, flash, send_file

app = Flask(__name__)
app.secret_key = "metrify"

DB = "database.db"


# -----------------------
# Conexão + inicialização
# -----------------------
def db():
    return sqlite3.connect(DB)


def init():
    con = db()
    c = con.cursor()

    # Produtos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            titulo TEXT,
            estoque INTEGER DEFAULT 0
        )
    """
    )

    # Garante coluna de custo unitário
    try:
        c.execute("ALTER TABLE produtos ADD COLUMN custo_unitario REAL DEFAULT 0")
    except sqlite3.OperationalError:
        # coluna já existe
        pass

    # Vendas consolidadas
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            titulo TEXT,
            quantidade INTEGER,
            receita REAL,
            comissao REAL,
            preco_medio REAL
        )
    """
    )

    # Movimentações de estoque (log)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS estoque_mov (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            data TEXT,
            tipo TEXT,           -- entrada / saida / ajuste
            quantidade REAL,
            obs TEXT
        )
    """
    )

    # Configurações (imposto e despesas)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            imposto_pct REAL DEFAULT 5.0,
            despesa_pct REAL DEFAULT 3.5
        )
    """
    )
    # Garante registro único
    c.execute("SELECT COUNT(*) FROM settings WHERE id = 1")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO settings (id, imposto_pct, despesa_pct) VALUES (1, 5.0, 3.5)"
        )

    con.commit()
    con.close()


init()


def get_settings():
    con = db()
    c = con.cursor()
    c.execute("SELECT imposto_pct, despesa_pct FROM settings WHERE id = 1")
    row = c.fetchone()
    con.close()
    if not row:
        return {"imposto_pct": 5.0, "despesa_pct": 3.5}
    return {"imposto_pct": row[0] or 0.0, "despesa_pct": row[1] or 0.0}


# -------------
# DASHBOARD
# -------------
@app.route("/")
def dashboard():
    con = db()
    c = con.cursor()

    # Totais de produtos / estoque
    c.execute("SELECT COUNT(*), IFNULL(SUM(estoque), 0) FROM produtos")
    total_produtos, estoque_total = c.fetchone()

    # Totais de vendas
    c.execute("SELECT IFNULL(SUM(receita), 0), IFNULL(SUM(comissao), 0) FROM vendas")
    receita_total, comissao_total = c.fetchone()

    con.close()

    return render_template(
        "dashboard.html",
        total_produtos=total_produtos,
        estoque_total=estoque_total,
        receita_total=receita_total,
        comissao_total=comissao_total,
    )


# -------------
# PRODUTOS
# -------------
@app.route("/produtos")
def produtos():
    con = db()
    c = con.cursor()
    c.execute("SELECT id, sku, titulo, estoque, IFNULL(custo_unitario,0) FROM produtos ORDER BY titulo")
    dados = c.fetchall()
    con.close()
    return render_template("produtos.html", produtos=dados)


@app.route("/add_produto", methods=["POST"])
def add_produto():
    sku = request.form["sku"].strip()
    titulo = request.form["titulo"].strip()
    est = int(request.form.get("estoque") or 0)
    custo_raw = request.form.get("custo_unitario") or "0"

    try:
        custo_unitario = float(str(custo_raw).replace(",", "."))
    except ValueError:
        custo_unitario = 0.0

    if not sku:
        flash("SKU é obrigatório", "danger")
        return redirect("/produtos")

    con = db()
    c = con.cursor()
    try:
        c.execute(
            "INSERT INTO produtos (sku, titulo, estoque, custo_unitario) VALUES (?, ?, ?, ?)",
            (sku, titulo, est, custo_unitario),
        )
        con.commit()
        flash("Produto cadastrado", "success")
    except sqlite3.IntegrityError:
        flash("SKU já existe, ajuste o produto existente.", "warning")
    finally:
        con.close()

    return redirect("/produtos")


@app.route("/produto/<int:id>/editar", methods=["GET", "POST"])
def produto_editar(id):
    con = db()
    c = con.cursor()

    if request.method == "POST":
        sku = request.form["sku"].strip()
        titulo = request.form["titulo"].strip()
        estoque = int(request.form.get("estoque") or 0)
        custo_raw = request.form.get("custo_unitario") or "0"

        try:
            custo_unitario = float(str(custo_raw).replace(",", "."))
        except ValueError:
            custo_unitario = 0.0

        try:
            c.execute(
                "UPDATE produtos SET sku = ?, titulo = ?, estoque = ?, custo_unitario = ? WHERE id = ?",
                (sku, titulo, estoque, custo_unitario, id),
            )
            con.commit()
            flash("Produto atualizado com sucesso.", "success")
        except sqlite3.IntegrityError:
            flash("Já existe outro produto com esse SKU.", "danger")
        finally:
            con.close()

        return redirect("/produtos")

    # GET -> carrega dados do produto
    c.execute("SELECT id, sku, titulo, estoque, IFNULL(custo_unitario,0) FROM produtos WHERE id = ?", (id,))
    produto = c.fetchone()
    con.close()

    if not produto:
        flash("Produto não encontrado.", "danger")
        return redirect("/produtos")

    return render_template("produto_editar.html", produto=produto)


@app.route("/produto/<int:id>/deletar", methods=["POST"])
def produto_deletar(id):
    con = db()
    c = con.cursor()
    c.execute("DELETE FROM produtos WHERE id = ?", (id,))
    con.commit()
    con.close()
    flash("Produto excluído.", "warning")
    return redirect("/produtos")


# -------------
# ESTOQUE (tela)
# -------------
@app.route("/estoque", methods=["GET"])
def estoque_page():
    con = db()
    c = con.cursor()
    c.execute("SELECT id, sku, titulo, estoque FROM produtos ORDER BY titulo")
    produtos = c.fetchall()

    # últimas movimentações
    c.execute(
        """
        SELECT sku, data, tipo, quantidade, obs 
        FROM estoque_mov
        ORDER BY id DESC
        LIMIT 50
    """
    )
    movs = c.fetchall()

    con.close()
    return render_template("estoque.html", produtos=produtos, movs=movs)


# -------------
# ESTOQUE (movimentação: entrada/saída/ajuste)
# -------------
@app.route("/estoque/movimento", methods=["POST"])
def estoque_movimento():
    sku = request.form["sku"].strip()
    tipo = request.form["tipo"]  # entrada / saida / ajuste
    qtd_raw = request.form.get("quantidade") or "0"
    obs = request.form.get("obs", "").strip()
    nova_qtd_raw = request.form.get("nova_qtd") or ""

    try:
        quantidade = float(str(qtd_raw).replace(",", ".")) if qtd_raw else 0
    except ValueError:
        quantidade = 0

    con = db()
    c = con.cursor()

    # Verifica se produto existe
    c.execute("SELECT estoque FROM produtos WHERE sku = ?", (sku,))
    row = c.fetchone()
    if not row:
        con.close()
        flash("SKU não encontrado.", "danger")
        return redirect("/estoque")

    estoque_atual = row[0] or 0
    data_hoje = datetime.now().strftime("%Y-%m-%d")

    if tipo in ("entrada", "saida"):
        if quantidade <= 0:
            con.close()
            flash("Quantidade deve ser maior que zero.", "danger")
            return redirect("/estoque")

        if tipo == "entrada":
            novo_estoque = estoque_atual + quantidade
        else:
            novo_estoque = estoque_atual - quantidade

        c.execute(
            "UPDATE produtos SET estoque = ? WHERE sku = ?", (novo_estoque, sku)
        )
        c.execute(
            """
            INSERT INTO estoque_mov (sku, data, tipo, quantidade, obs)
            VALUES (?, ?, ?, ?, ?)
        """,
            (sku, data_hoje, tipo, quantidade, obs),
        )
        con.commit()
        con.close()
        flash("Movimentação registrada.", "success")
        return redirect("/estoque")

    elif tipo == "ajuste":
        # Ajuste leva em conta a quantidade final desejada
        if not nova_qtd_raw:
            con.close()
            flash("Informe a nova quantidade para ajuste.", "danger")
            return redirect("/estoque")

        try:
            nova_qtd = float(str(nova_qtd_raw).replace(",", "."))
        except ValueError:
            con.close()
            flash("Nova quantidade inválida.", "danger")
            return redirect("/estoque")

        diff = nova_qtd - estoque_atual
        if abs(diff) < 0.0001:
            con.close()
            flash("Estoque já está na quantidade informada.", "info")
            return redirect("/estoque")

        # Aplica ajuste
        c.execute("UPDATE produtos SET estoque = ? WHERE sku = ?", (nova_qtd, sku))
        c.execute(
            """
            INSERT INTO estoque_mov (sku, data, tipo, quantidade, obs)
            VALUES (?, ?, ?, ?, ?)
        """,
            (sku, data_hoje, "ajuste", diff, obs),
        )
        con.commit()
        con.close()
        flash("Ajuste de estoque aplicado.", "success")
        return redirect("/estoque")

    else:
        con.close()
        flash("Tipo de movimentação inválido.", "danger")
        return redirect("/estoque")


# -------------
# EXPORTAR TEMPLATE PARA CONSOLIDAÇÃO (IMPORTAÇÃO)
# -------------
@app.route("/exportar_template")
def exportar_template():
    cols = ["SKU", "Titulo", "Quantidade", "Receita", "Comissao", "PrecoMedio"]
    df = pd.DataFrame(columns=cols)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Template")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="template_consolidacao.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# -------------
# IMPORTAR VENDAS + ATUALIZAR ESTOQUE + CRIAR PRODUTOS
# -------------
@app.route("/importar", methods=["GET", "POST"])
def importar():
    if request.method == "POST":
        if "arquivo" not in request.files:
            flash("Nenhum arquivo enviado.", "danger")
            return redirect("/importar")

        arq = request.files["arquivo"]

        try:
            df = pd.read_excel(arq)
        except Exception as e:
            flash(f"Erro ao ler a planilha: {e}", "danger")
            return redirect("/importar")

        colunas_esperadas = {"SKU", "Titulo", "Quantidade", "Receita", "Comissao"}
        if not colunas_esperadas.issubset(df.columns):
            flash(
                "Planilha inválida. Use o template gerado pelo sistema.", "danger"
            )
            return redirect("/importar")

        con = db()
        c = con.cursor()

        for _, r in df.iterrows():
            sku = str(r["SKU"]).strip()
            titulo = str(r["Titulo"]).strip()
            qtd = int(r["Quantidade"] or 0)
            receita = float(r["Receita"] or 0)
            comissao = float(r["Comissao"] or 0)
            preco_medio = float(r.get("PrecoMedio", 0) or 0)

            if not sku or qtd <= 0:
                continue

            # Garante produto
            c.execute("SELECT id FROM produtos WHERE sku = ?", (sku,))
            row = c.fetchone()
            if not row:
                c.execute(
                    "INSERT INTO produtos (sku, titulo, estoque, custo_unitario) VALUES (?, ?, ?, ?)",
                    (sku, titulo, 0, 0.0),
                )
            else:
                # opcional: atualiza título se mudou
                if titulo:
                    c.execute(
                        "UPDATE produtos SET titulo = ? WHERE sku = ?", (titulo, sku)
                    )

            # Registra venda
            c.execute(
                """
                INSERT INTO vendas (sku, titulo, quantidade, receita, comissao, preco_medio)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (sku, titulo, qtd, receita, comissao, preco_medio),
            )

            # Baixa estoque
            c.execute(
                "UPDATE produtos SET estoque = IFNULL(estoque,0) - ? WHERE sku = ?",
                (qtd, sku),
            )

            # Log de movimentação (saída por venda importada)
            data_hoje = datetime.now().strftime("%Y-%m-%d")
            c.execute(
                """
                INSERT INTO estoque_mov (sku, data, tipo, quantidade, obs)
                VALUES (?, ?, ?, ?, ?)
            """,
                (sku, data_hoje, "saida", qtd, "Venda importada"),
            )

        con.commit()
        con.close()

        flash(
            "Importação concluída, vendas registradas e estoque atualizado.", "success"
        )
        return redirect("/importar")

    return render_template("importar.html")


# -------------
# CONFIGURAÇÕES (impostos e despesas)
# -------------
@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        imposto_pct = float(request.form.get("imposto_pct") or 0)
        despesa_pct = float(request.form.get("despesa_pct") or 0)

        con = db()
        c = con.cursor()
        c.execute(
            "UPDATE settings SET imposto_pct = ?, despesa_pct = ? WHERE id = 1",
            (imposto_pct, despesa_pct),
        )
        con.commit()
        con.close()
        flash("Configurações salvas.", "success")
        return redirect("/configuracoes")

    cfg = get_settings()
    return render_template(
        "configuracoes.html",
        imposto_pct=cfg["imposto_pct"],
        despesa_pct=cfg["despesa_pct"],
    )


# -------------
# RELATÓRIO CONSOLIDADO COM TOTAIS, IMPOSTO, DESPESAS, CUSTO E LUCRO
# -------------
@app.route("/relatorio")
def relatorio():
    cfg = get_settings()
    imposto_pct = cfg["imposto_pct"] / 100.0
    despesa_pct = cfg["despesa_pct"] / 100.0

    con = db()
    c = con.cursor()
    c.execute(
        """
        SELECT sku,
               titulo,
               SUM(quantidade) AS qtd,
               SUM(receita)   AS receita,
               SUM(comissao)  AS comissao,
               AVG(preco_medio) AS preco_med
        FROM vendas
        GROUP BY sku, titulo
    """
    )
    rows = c.fetchall()

    # Mapa de custos por SKU
    c.execute("SELECT sku, IFNULL(custo_unitario,0) FROM produtos")
    custos_raw = c.fetchall()
    con.close()

    custos = {r[0]: r[1] for r in custos_raw}

    dados = []
    total_qtd = 0
    total_receita = 0
    total_comissao = 0
    total_imposto = 0
    total_despesa = 0
    total_custo_total = 0
    total_lucro = 0

    for r in rows:
        sku, titulo, qtd, receita, comissao, preco_med = r
        qtd = qtd or 0
        receita = receita or 0
        comissao = comissao or 0
        preco_med = preco_med or 0

        custo_unit = custos.get(sku, 0) or 0
        custo_total = custo_unit * qtd

        imposto = receita * imposto_pct
        base_liquida = max(receita - comissao, 0)
        despesa = base_liquida * despesa_pct

        lucro = receita - (comissao + imposto + despesa + custo_total)

        dados.append(
            {
                "sku": sku,
                "titulo": titulo,
                "qtd": qtd,
                "receita": receita,
                "comissao": comissao,
                "imposto": imposto,
                "despesa": despesa,
                "custo_unit": custo_unit,
                "custo_total": custo_total,
                "lucro": lucro,
                "preco_med": preco_med,
            }
        )

        total_qtd += qtd
        total_receita += receita
        total_comissao += comissao
        total_imposto += imposto
        total_despesa += despesa
        total_custo_total += custo_total
        total_lucro += lucro

    # Ordena por lucro (margem) decrescente
    dados = sorted(dados, key=lambda d: d["lucro"], reverse=True)

    totais = {
        "qtd": total_qtd,
        "receita": total_receita,
        "comissao": total_comissao,
        "imposto": total_imposto,
        "despesa": total_despesa,
        "custo_total": total_custo_total,
        "lucro": total_lucro,
    }

    return render_template("relatorio.html", dados=dados, totais=totais, cfg=cfg)


# -------------
# EXPORTAR RELATÓRIO COMPLETO PARA EXCEL (COM CUSTO E LUCRO)
# -------------
@app.route("/exportar_relatorio")
def exportar_relatorio():
    cfg = get_settings()
    imposto_pct = cfg["imposto_pct"] / 100.0
    despesa_pct = cfg["despesa_pct"] / 100.0

    con = db()
    c = con.cursor()
    c.execute(
        """
        SELECT sku,
               titulo,
               SUM(quantidade) AS qtd,
               SUM(receita)   AS receita,
               SUM(comissao)  AS comissao,
               AVG(preco_medio) AS preco_med
        FROM vendas
        GROUP BY sku, titulo
    """
    )
    rows = c.fetchall()

    # custos
    c.execute("SELECT sku, IFNULL(custo_unitario,0) FROM produtos")
    custos_raw = c.fetchall()
    con.close()
    custos = {r[0]: r[1] for r in custos_raw}

    registros = []
    for r in rows:
        sku, titulo, qtd, receita, comissao, preco_med = r
        qtd = qtd or 0
        receita = receita or 0
        comissao = comissao or 0
        preco_med = preco_med or 0

        custo_unit = custos.get(sku, 0) or 0
        custo_total = custo_unit * qtd

        imposto = receita * imposto_pct
        base_liquida = max(receita - comissao, 0)
        despesa = base_liquida * despesa_pct
        lucro = receita - (comissao + imposto + despesa + custo_total)

        registros.append(
            {
                "SKU": sku,
                "Titulo": titulo,
                "Quantidade": qtd,
                "Receita": receita,
                "Comissao": comissao,
                "Imposto": imposto,
                "Despesas": despesa,
                "CustoUnitario": custo_unit,
                "CustoTotal": custo_total,
                "Lucro": lucro,
                "PrecoMedioVenda": preco_med,
            }
        )

    df = pd.DataFrame(registros)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="RelatorioLucro")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="relatorio_lucro_metrify.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
