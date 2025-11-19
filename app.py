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

@app.route('/importar', methods=['GET','POST'])
def importar():
    if request.method == 'POST':
        arq = request.files['arquivo']
        df = pd.read_excel(arq)
        con = db(); c = con.cursor()
        for _, r in df.iterrows():
            c.execute("INSERT INTO vendas(sku,titulo,quantidade,receita,comissao,preco_medio) VALUES (?,?,?,?,?,?)",
                      (r['SKU'], r['Titulo'], int(r['Quantidade']), float(r['Receita']),
                       float(r['Comissao']), float(r.get('PrecoMedio', 0))))
        con.commit(); con.close()
        flash("Importado!")
        return redirect('/importar')
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
