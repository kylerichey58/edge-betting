import os, re

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Total lines:", len(lines))

# The duplicates are:
# 'msg'   at lines 2188 and 2258
# 'sign'  at lines 2195 and 2271  
# 'color' at lines 2196 and 2270
# The SECOND occurrence of each needs 'var' removed

# Fix: on the second occurrence lines, remove 'var ' prefix
fixes = {
    2258: 'msg',
    2271: 'sign', 
    2270: 'color',
}

for line_num, varname in fixes.items():
    idx = line_num - 1  # convert to 0-based
    if idx < len(lines):
        old_line = lines[idx]
        # Remove 'var ' from this specific line
        new_line = old_line.replace('var ' + varname + ' =', varname + ' =', 1)
        if new_line != old_line:
            lines[idx] = new_line
            print("Fixed line", line_num, ":", repr(old_line.strip()[:60]), "->", repr(new_line.strip()[:60]))
        else:
            print("Line", line_num, "- pattern not found:", repr(old_line.strip()[:80]))

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("\nDone!")
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then click tabs!")
