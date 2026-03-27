import os, re

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Total lines:", len(lines))
fixes = 0

# The specific lines causing cross-scope conflicts
# These are var declarations that conflict with const/let in same function scope
# Fix: change var -> just assignment (no keyword) on the LATER duplicate

problem_lines = {
    # line_num: description
    2186: "var pl = bets.reduce",
    2218: "var val = document.createElement",
}

for line_num, desc in problem_lines.items():
    idx = line_num - 1
    if idx < len(lines):
        line = lines[idx]
        if 'var pl' in line:
            lines[idx] = line.replace('var pl ', 'pl ', 1)
            print(f"Fixed line {line_num}: removed 'var' from pl")
            fixes += 1
        elif 'var val' in line:
            lines[idx] = line.replace('var val ', 'val ', 1)
            print(f"Fixed line {line_num}: removed 'var' from val")
            fixes += 1

# Also fix the renderTodaySnapshot var declarations that conflict
# Look for var badge, var title, var card in renderTodaySnapshot
in_snapshot = False
snapshot_vars_seen = set()
for i, line in enumerate(lines):
    if 'function renderTodaySnapshot()' in line:
        in_snapshot = True
        snapshot_vars_seen = set()
    elif in_snapshot and line.strip().startswith('}') and line.strip() == '}':
        in_snapshot = False
    elif in_snapshot:
        m = re.match(r'\s+var (\w+)\s*=', line)
        if m:
            varname = m.group(1)
            if varname in snapshot_vars_seen:
                lines[i] = line.replace('var ' + varname + ' ', varname + ' ', 1)
                print(f"Fixed dup var '{varname}' at line {i+1}")
                fixes += 1
            else:
                snapshot_vars_seen.add(varname)

# Fix the renderBankroll function - find duplicate var declarations within it
in_bankroll = False
bankroll_vars_seen = set()
for i, line in enumerate(lines):
    if 'function renderBankroll()' in line:
        in_bankroll = True
        bankroll_vars_seen = set()
    elif in_bankroll and re.match(r'^}\s*$', line):
        in_bankroll = False
    elif in_bankroll:
        m = re.match(r'\s+(var|let|const) (\w+)\s*=', line)
        if m:
            kw, varname = m.group(1), m.group(2)
            key = varname
            if key in bankroll_vars_seen:
                old = m.group(0)
                new = old.replace(kw + ' ' + varname, varname)
                lines[i] = lines[i].replace(old, new, 1)
                print(f"Fixed dup '{varname}' in renderBankroll at line {i+1}")
                fixes += 1
            else:
                bankroll_vars_seen.add(key)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\nTotal fixes: {fixes}")
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then check bet tracker!")
