import os, re
from datetime import date

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Original size:", len(content))
fixes = 0

# FIX 1: Update date to today
old_date = "March 13, 2026"
new_date = "March 14, 2026"
if old_date in content:
    content = content.replace(old_date, new_date)
    print("FIX 1: Date updated to March 14, 2026")
    fixes += 1
else:
    print("FIX 1: Date not found")

# FIX 2: Add the 4 new bets to the BETS array
# Find the last bet in the array and add after it
# The array ends with }]; - find the last entry
last_bet_marker = "  {id:58,"
if last_bet_marker not in content:
    # Try to find the end of the BETS array
    last_bet_marker = content[content.rfind('{id:'):content.rfind('{id:')+10]
    print("Last bet marker:", last_bet_marker)

# Find where BETS array ends
bets_end = content.rfind('];\n\n// ─── SAVED BETS')
if bets_end == -1:
    bets_end = content.rfind('];\n\nlet savedBets')
if bets_end == -1:
    bets_end = content.rfind('];\n\n// ─')
    
print("BETS array end at:", bets_end)
print("Content there:", repr(content[bets_end-50:bets_end+30]))

if bets_end != -1:
    new_bets = """,
  {id:59,date:"3/14/2026",game:"Purdue @ Nebraska",pick:"Nebraska +4.5",sport:"NCAAM",type:"SPREAD",odds:"-108",units:1.0,stars:4,pl:-1.0,result:"LOSS"},
  {id:60,date:"3/14/2026",game:"Purdue @ Nebraska",pick:"UNDER 145.5",sport:"NCAAM",type:"TOTAL",odds:"-108",units:1.0,stars:4,pl:0.93,result:"WIN"},
  {id:61,date:"3/14/2026",game:"Kansas @ Houston",pick:"UNDER 139.5",sport:"NCAAM",type:"TOTAL",odds:"-115",units:1.0,stars:4,pl:0.87,result:"WIN"},
  {id:62,date:"3/14/2026",game:"UCLA @ Michigan St.",pick:"UNDER 141.5",sport:"NCAAM",type:"TOTAL",odds:"-108",units:0.92,stars:3,pl:-0.92,result:"LOSS"}"""
    
    content = content[:bets_end] + new_bets + content[bets_end:]
    print("FIX 2: 4 new bets added (IDs 59-62)")
    fixes += 1
else:
    print("FIX 2: Could not find end of BETS array")

# FIX 3: Update the stats in the header to reflect new record
# Old: 33W-24L-1P | New: 34W-26L-1P (added 2W 2L)
# Also update win rate, net units etc
replacements = [
    ("33W-24L-1P", "34W-26L-1P"),
    ('"33W · 24L · 1P"', '"34W · 26L · 1P"'),
    ("33W · 24L · 1P", "34W · 26L · 1P"),
    ("33W-24L-1P", "34W-26L-1P"),
]
for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print("FIX 3: Record updated:", old, "->", new)
        fixes += 1
        break

# Update BETS GRADED ticker
content = content.replace("BETS GRADED <span class=\"t-green\">68 TOTAL</span>",
                          "BETS GRADED <span class=\"t-green\">72 TOTAL</span>")
print("FIX 4: Ticker updated to 72 total bets")
fixes += 1

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("\nDone! Fixes:", fixes)
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R to reload!")
