import os

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Let's fix lines 208 and 209 specifically first to see
# 208:     if not config.app.get("hide_config", False):
# 209:         with st.expander(tr("Basic Settings"), expanded=False):

lines[207] = "    if not config.app.get(\"hide_config\", False):\n"
lines[208] = "        with st.expander(tr(\"Basic Settings\"), expanded=False):\n"

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Manually set indentation for lines 208 and 209")
