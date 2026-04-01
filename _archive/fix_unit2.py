import os, re

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find ALL declarations of 'unit' variable
print("All 'unit' declarations:")
for i, line in enumerate(lines):
    if re.search(r'\b(const|let|var)\s+unit\b', line):
        print(f"  Line {i+1}: {repr(line.strip()[:80])}")

# The fix: in modern JS (const/let), var in same scope = error
# Change ALL unit declarations to use consistent 'var'
# OR change the const/let ones to match
fixed = 0
for i, line in enumerate(lines):
    # Change 'const unit = ' to 'var unit = '
    if 'const unit = bankroll.unit' in line or 'const unit = bankroll' in line:
        lines[i] = line.replace('const unit =', 'var unit =', 1)
        print(f"Fixed const->var at line {i+1}")
        fixed += 1
    # Change 'let unit = ' to 'var unit = '
    elif 'let unit = bankroll.unit' in line or 'let unit = bankroll' in line:
        lines[i] = line.replace('let unit =', 'var unit =', 1)
        print(f"Fixed let->var at line {i+1}")
        fixed += 1

# Now deduplicate - keep first var unit, rest become just unit =
first_found = False
for i, line in enumerate(lines):
    if 'var unit = bankroll.unit' in line:
        if first_found:
            lines[i] = line.replace('var unit =', 'unit =', 1)
            print(f"Removed dup var unit at line {i+1}")
            fixed += 1
        else:
            first_found = True

print(f"\nTotal fixes: {fixed}")

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done!")
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then test tabs!")
