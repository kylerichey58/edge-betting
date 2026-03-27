import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Size:", len(content))

# Check if renderTracker exists
if 'function renderTracker()' in content:
    print("renderTracker function: EXISTS")
else:
    print("renderTracker function: MISSING - this is the problem!")

# Check if tracker-body exists in HTML
if 'id="tracker-body"' in content:
    print("tracker-body element: EXISTS")
else:
    print("tracker-body element: MISSING")

# Check if BETS array has data
bets_idx = content.find('const BETS = [')
if bets_idx != -1:
    # Count how many bet entries
    import re
    bets = re.findall(r'\{id:\d+,', content)
    print("Bets in array:", len(bets))
else:
    print("BETS array: NOT FOUND")

# Check if renderTracker is called on DOMContentLoaded
if 'renderTracker()' in content:
    print("renderTracker() calls found:", content.count('renderTracker()'))
else:
    print("renderTracker() never called!")

# Check currentSport and currentType variables
if 'currentSport' in content:
    idx = content.find("let currentSport")
    if idx == -1:
        idx = content.find("var currentSport")
    print("currentSport declaration:", repr(content[idx:idx+60]) if idx != -1 else "NOT FOUND")
else:
    print("currentSport: NOT FOUND - this could be the bug!")
