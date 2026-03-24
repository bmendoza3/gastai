from src.reports.charts import spend_bar_chart, spend_pie_chart

phone = "+56912345678"

buf = spend_bar_chart(user_phone=phone, days_back=30)
with open("/tmp/gastai_bar.png", "wb") as f:
    f.write(buf.read())
print("Bar chart → /tmp/gastai_bar.png")

buf = spend_pie_chart(user_phone=phone, days_back=30)
with open("/tmp/gastai_pie.png", "wb") as f:
    f.write(buf.read())
print("Pie chart → /tmp/gastai_pie.png")
