import re
f = 'webapp/index.html'
with open(f, encoding='utf-8') as fh:
    t = fh.read()

# Replace "1 🍑" with "150 🍑" in pic_cost and pic_generate strings
t = t.replace("pic_cost: 'One picture — 1 🍑'", "pic_cost: 'One picture — 150 🍑'")
t = t.replace("pic_generate: 'Create · 1 🍑'", "pic_generate: 'Create · 150 '")
t = t.replace("pic_cost: 'Одна картинка — 1 🍑'", "pic_cost: 'Одна картинка — 150 🍑'")
t = t.replace("pic_generate: 'Создать · 1 🍑'", "pic_generate: 'Создать · 150 🍑'")
t = t.replace("pic_cost: 'Una imagen — 1 🍑'", "pic_cost: 'Una imagen — 150 🍑'")
t = t.replace("pic_generate: 'Crear · 1 🍑'", "pic_generate: 'Crear · 150 🍑'")
t = t.replace("pic_cost: 'Un\\'immagine — 1 🍑'", "pic_cost: 'Un\\'immagine — 150 🍑'")
t = t.replace("pic_generate: 'Crea · 1 🍑'", "pic_generate: 'Crea · 150 🍑'")
t = t.replace("pic_cost: 'Une image — 1 🍑'", "pic_cost: 'Une image — 150 🍑'")
t = t.replace("pic_generate: 'Créer · 1 🍑'", "pic_generate: 'Créer · 150 🍑'")
t = t.replace("pic_cost: '一张图片 — 1 🍑'", "pic_cost: '一张图片 — 150 🍑'")
t = t.replace("pic_generate: '创建 · 1 🍑'", "pic_generate: '创建 · 150 🍑'")
t = t.replace("pic_cost: '1枚 — 1 🍑'", "pic_cost: '1枚 — 150 🍑'")
t = t.replace("pic_generate: '作成 · 1 🍑'", "pic_generate: '作成 · 150 🍑'")

with open(f, 'w', encoding='utf-8') as fh:
    fh.write(t)
print('Done - updated pic_cost and pic_generate to 150')
