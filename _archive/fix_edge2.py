import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')
print("Reading:", path)

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Original size:", len(content))
changes = 0

# STEP 1: Nuke the entire ledger renderer and replace with simple DOM version
ledger_marker = "// Group by date"
ledger_start = content.find(ledger_marker)
if ledger_start == -1:
    ledger_start = content.find("// Group transactions")

if ledger_start != -1:
    # Find where it ends - look for the next top-level function
    rb_end = content.find("\n}\n\n// ", ledger_start)
    if rb_end == -1:
        rb_end = content.find("\n}\n\nfunction ", ledger_start)
    
    if rb_end != -1:
        simple_ledger = """  // Simple ledger renderer - no complex string escaping
  ledger.innerHTML = "";
  var unit = bankroll.unit || 20;
  if(txns.length === 0) {
    var msg = document.createElement("div");
    msg.style.cssText = "color:var(--text3);text-align:center;padding:40px 0";
    msg.textContent = "No transactions yet. Log a deposit to start.";
    ledger.appendChild(msg);
    return;
  }
  txns.slice().reverse().forEach(function(t) {
    var isD = t.type === "Deposit";
    var isW = t.type === "Withdrawal";
    var isB = t.type === "Bet";
    var isWin = isB && t.pl > 0;
    var isLoss = isB && t.pl < 0;
    var color = isD ? "var(--green)" : isW ? "var(--red)" : isWin ? "var(--green)" : isLoss ? "var(--red)" : "var(--text3)";
    var sign = isD ? "+" : isW ? "-" : (t.pl >= 0 ? "+" : "");
    var amt = isB ? (sign + "$" + Math.abs(t.pl * unit).toFixed(2)) : (sign + "$" + t.amount.toFixed(2));
    var bal = t.balanceAfter !== undefined ? "$" + t.balanceAfter.toFixed(2) : "-";
    var label = isD ? "DEPOSIT" : isW ? "WITHDRAW" : isWin ? "WIN" : isLoss ? "LOSS" : "PUSH";

    var row = document.createElement("div");
    row.style.cssText = "display:grid;grid-template-columns:80px 1fr 90px 90px;gap:4px;padding:9px 0;border-bottom:1px solid var(--border);align-items:center";

    var dateEl = document.createElement("div");
    dateEl.style.cssText = "font-size:11px;color:var(--text3)";
    dateEl.textContent = t.date || "";

    var infoEl = document.createElement("div");
    var labelEl = document.createElement("div");
    labelEl.style.cssText = "font-size:12px;color:" + color + ";font-weight:700";
    labelEl.textContent = label;
    var noteEl = document.createElement("div");
    noteEl.style.cssText = "font-size:11px;color:var(--text3)";
    noteEl.textContent = t.note || "";
    infoEl.appendChild(labelEl);
    infoEl.appendChild(noteEl);

    var amtEl = document.createElement("div");
    amtEl.style.cssText = "font-size:13px;color:" + color + ";font-weight:700;text-align:right";
    amtEl.textContent = amt;

    var balEl = document.createElement("div");
    balEl.style.cssText = "font-size:13px;color:var(--text);text-align:right";
    balEl.textContent = bal;

    row.appendChild(dateEl);
    row.appendChild(infoEl);
    row.appendChild(amtEl);
    row.appendChild(balEl);
    ledger.appendChild(row);
  });"""
        content = content[:ledger_start] + simple_ledger + content[rb_end:]
        print("FIX 1: Ledger renderer replaced with simple DOM version")
        changes += 1
    else:
        print("FIX 1: Could not find ledger end")
else:
    print("FIX 1: Ledger section not found")

# STEP 2: Replace renderTodaySnapshot with simple version
snap_start = content.find("function renderTodaySnapshot()")
if snap_start != -1:
    snap_end = content.find("\n}\n\n", snap_start)
    if snap_end != -1:
        snap_end += 4
        simple_snap = """function renderTodaySnapshot() {
  var card = document.getElementById("today-snap-body");
  var badge = document.getElementById("today-snap-badge");
  var title = document.getElementById("today-snap-title");
  if (!card) return;
  var todayStr = new Date().toLocaleDateString();
  var bets = (bankroll.transactions || []).filter(function(t) { return t.type === "Bet" && t.date === todayStr; });
  var pl = bets.reduce(function(s, t) { return s + (t.pl || 0) * (bankroll.unit || 20); }, 0);
  var wins = bets.filter(function(t) { return t.pl > 0; }).length;
  var losses = bets.filter(function(t) { return t.pl < 0; }).length;
  if (title) title.textContent = "Today - " + todayStr;
  if (bets.length === 0) {
    card.innerHTML = "";
    var msg = document.createElement("div");
    msg.style.cssText = "color:var(--text3);padding:8px 0;font-size:13px";
    msg.textContent = "No bets today. Log a deposit and grade bets to start tracking.";
    card.appendChild(msg);
    if (badge) { badge.textContent = "No Activity"; badge.className = "badge gray"; }
    return;
  }
  var sign = pl >= 0 ? "+" : "";
  var color = pl > 0 ? "var(--green)" : pl < 0 ? "var(--red)" : "var(--text3)";
  if (badge) {
    badge.textContent = sign + "$" + pl.toFixed(2);
    badge.className = "badge " + (pl > 0 ? "green" : pl < 0 ? "red" : "gray");
  }
  card.innerHTML = "";
  var summary = document.createElement("div");
  summary.style.cssText = "display:flex;gap:20px;flex-wrap:wrap";
  var items = [
    ["P/L", sign + "$" + pl.toFixed(2), color],
    ["RECORD", wins + "W - " + losses + "L", "var(--text)"],
    ["BALANCE", "$" + bankroll.balance.toFixed(2), "var(--gold)"]
  ];
  items.forEach(function(item) {
    var box = document.createElement("div");
    var lbl = document.createElement("div");
    lbl.style.cssText = "font-size:10px;color:var(--text3);font-family:var(--font-mono)";
    lbl.textContent = item[0];
    var val = document.createElement("div");
    val.style.cssText = "font-size:18px;color:" + item[2] + ";font-weight:700";
    val.textContent = item[1];
    box.appendChild(lbl);
    box.appendChild(val);
    summary.appendChild(box);
  });
  card.appendChild(summary);
}

"""
        content = content[:snap_start] + simple_snap + content[snap_end:]
        print("FIX 2: renderTodaySnapshot replaced")
        changes += 1
    else:
        print("FIX 2: Could not find end of renderTodaySnapshot")
else:
    print("FIX 2: renderTodaySnapshot not found")

# STEP 3: Stub out toggleDay
toggle_start = content.find("function toggleDay(dayId)")
if toggle_start == -1:
    toggle_start = content.find("function toggleDay(id)")
if toggle_start != -1:
    toggle_end = content.find("\n}\n", toggle_start) + 3
    content = content[:toggle_start] + "function toggleDay(id) { /* stub */ }\n" + content[toggle_end:]
    print("FIX 3: toggleDay stubbed out")
    changes += 1
else:
    print("FIX 3: toggleDay not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("")
print("Done! Changes:", changes)
print("New size:", len(content))
print("")
print("Go to Chrome: http://localhost:8080/EDGE-Platform.html")
print("Press Ctrl+Shift+R and click the tabs!")
