import os, io, sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, flash, send_file

app = Flask(__name__)
app.secret_key = "metrify"
DB = 'database.db'

def db():
    return sqlite3.connect(DB)

def init():
    con = db(); c = con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS produtos(id INTEGER PRIMARY KEY, sku TEXT, titulo TEXT, estoque INTEGER)")
    c.execute("""CREATE TABLE IF NOT EXISTS vendas(
        id INTEGER PRIMARY KEY,
        sku TEXT, titulo TEXT,
        quantidade INTEGER,
        receita REAL, comissao REAL, preco_medio REAL
    )""")
    con.commit(); con.close()

init()

@app.route('/')
def dashboard():
    con = db(); c = con.cursor()
    c.execute("SELECT COUNT(*), IFNULL(SUM(estoque),0) FROM produtos")
    total_prod, estoque = c.fetchone()
    c.execute("SELECT IFNULL(SUM(receita),0), IFNULL(SUM(comissao),0) FROM vendas")
    receita, comissao = c.fetchone()
    con.close()
    return render_template('dashboard.html',
                           total_produtos=total_prod,
                           estoque_total=estoque,
                           receita_total=receita,
                           comissao_total=comissao)

@app.route('/produtos')
def produtos():
    con = db(); c = con.cursor()
    c.execute("SELECT * FROM produtos")
    dados = c.fetchall(); con.close()
    return render_template('produtos.html', produtos=dados)

@app.route('/add_produto', methods=['POST'])
def add_produto():
    sku = request.form['sku']; titulo = request.form['titulo']; est = int(request.form['estoque'] or 0)
    con = db(); c = con.cursor()
    c.execute("INSERT INTO produtos (sku,titulo,estoque) VALUES (?,?,?)",(sku,titulo,est))
    con.commit(); con.close()
    flash("Produto cadastrado")
    return redirect('/produtos')

@app.route('/estoque', methods=['POST'])
def estoque():
    sku = request.form['sku']; qtd = int(request.form['quantidade'] or 0); tipo = request.form['tipo']
    con = db(); c = con.cursor()
    if tipo == 'entrada':
        c.execute("UPDATE produtos SET estoque=estoque+? WHERE sku=?",(qtd,sku))
    else:
        c.execute("UPDATE produtos SET estoque=estoque-? WHERE sku=?",(qtd,sku))
    con.commit(); con.close()
    flash("Estoque atualizado")
    return redirect('/produtos')

@app.route('/importar', methods=['GET', 'POST'])
def importar():
    if request.method == 'POST':
        if 'arquivo' not in request.files:
            flash("Nenhum arquivo enviado.", "danger")
            return redirect('/importar')

        arq = request.files['arquivo']

        try:
            df = pd.read_excel(arq)
        except Exception as e:
            flash(f"Erro ao ler a planilha: {e}", "danger")
            return redirect('/importar')

        # Espera colunas: SKU, Titulo, Quantidade, Receita, Comissao, PrecoMedio
        colunas_esperadas = {'SKU', 'Titulo', 'Quantidade', 'Receita', 'Comissao'}
        if not colunas_esperadas.issubset(df.columns):
            flash("Planilha inválida. Use o template gerado pelo sistema.", "danger")
            return redirect('/importar')

        con = db()
        c = con.cursor()

        for _, r in df.iterrows():
            sku = str(r['SKU']).strip()
            titulo = str(r['Titulo']).strip()
            qtd = int(r['Quantidade'] or 0)
            receita = float(r['Receita'] or 0)
            comissao = float(r['Comissao'] or 0)
            preco_medio = float(r.get('PrecoMedio', 0) or 0)

            if not sku or qtd <= 0:
                # pula linhas sem SKU ou sem quantidade
                continue

            # 1) garante que o produto exista na tabela produtos
            c.execute("SELECT id FROM produtos WHERE sku = ?", (sku,))
            row = c.fetchone()

            if row is None:
                # cria produto novo com estoque inicial 0
                c.execute(
                    "INSERT INTO produtos (sku, titulo, estoque) VALUES (?,?,?)",
                    (sku, titulo, 0)
                )
            else:
                # opcional: atualiza título se tiver mudado
                c.execute(
                    "UPDATE produtos SET titulo = ? WHERE sku = ? AND (? IS NOT NULL AND ? != '')",
                    (titulo, sku, titulo, titulo)
                )

            # 2) lança a venda
            c.execute(
                """
                INSERT INTO vendas (sku, titulo, quantidade, receita, comissao, preco_medio)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sku, titulo, qtd, receita, comissao, preco_medio)
            )

            # 3) baixa o estoque (movimentação de saída)
            c.execute(
                "UPDATE produtos SET estoque = IFNULL(estoque,0) - ? WHERE sku = ?",
                (qtd, sku)
            )

        con.commit()
        con.close()

        flash("Importação concluída, vendas registradas e estoque atualizado.", "success")
        return redirect('/importar')

    # GET → só mostra a tela
    return render_template('importar.html')

@app.route('/exportar_template')
def exportar_template():
    cols = ['SKU','Titulo','Quantidade','Receita','Comissao','PrecoMedio']
    df = pd.DataFrame(columns=cols)
    buf = io.BytesIO()
    df.to_excel(buf, index=False); buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name="template_consol.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/relatorio')
def relatorio():
    con = db(); c = con.cursor()
    c.execute("SELECT sku,titulo,SUM(quantidade),SUM(receita),SUM(comissao),AVG(preco_medio) FROM vendas GROUP BY sku,titulo")
    dados = c.fetchall(); con.close()
    return render_template('relatorio.html', dados=dados)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
