import duckdb
con = duckdb.connect("data/finanzas.duckdb")
print(con.execute("SELECT * FROM transactions").fetchdf())