import os, re

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Size:", len(content))

# The tracker is empty because renderTracker uses const/let inside a .map()
# which is fine, but something is causing it to fail silently
# Let's replace renderTracker with a bulletproof version using forEach

old_tracker_start = "function renderTracker() {"
idx = content.find(old_tracker_start)
idx_end = content.find("\n}\n\n// ─── BANKROLL", idx)
if idx_end == -1:
    idx_end = content.find("\n}\n\nfunction filterTracker", idx)
if idx_end == -1:
    idx_end = content.find("\n}\n\nfunction filterType", idx)

print("renderTracker found at:", idx)
print("renderTracker ends at:", idx_end)
print("End context:", repr(content[idx_end:idx_end+60]))

new_tracker = '''function renderTracker() {
  var allBets = BETS.concat(savedBets);
  var filtered = allBets;
  if(currentSport !== 'ALL') filtered = filtered.filter(function(b){ return b.sport === currentSport; });
  if(currentType !== 'ALL') filtered = filtered.filter(function(b){ return b.type === currentType; });

  var tbody = document.getElementById('tracker-body');
  if(!tbody) return;
  tbody.innerHTML = '';

  filtered.forEach(function(b, i) {
    var plClass = b.pl > 0 ? 'win' : b.pl < 0 ? 'loss' : 'push';
    var plStr = b.pl > 0 ? '+'+b.pl.toFixed(2)+'u' : b.pl.toFixed(2)+'u';
    var starsStr = '';
    for(var s=0;s<(b.stars||3);s++) starsStr += '★';
    var savedIdx = savedBets.indexOf(b);
    var isPending = b.result === 'PENDING' || !b.result;

    var resHtml = '';
    if(b.result === 'WIN') resHtml = '<span class="badge green">WIN</span>';
    else if(b.result === 'LOSS') resHtml = '<span class="badge red">LOSS</span>';
    else if(b.result === 'PUSH') resHtml = '<span class="badge gray">PUSH</span>';
    else if(savedIdx !== -1) {
      resHtml = '<div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end">'
        + '<select id="grade-result-'+savedIdx+'" style="background:var(--bg3);border:1px solid var(--border2);border-radius:5px;padding:3px 6px;color:var(--text);font-family:var(--font-mono);font-size:11px">'
        + '<option value="">Result...</option>'
        + '<option value="WIN">WIN</option>'
        + '<option value="LOSS">LOSS</option>'
        + '<option value="PUSH">PUSH</option>'
        + '</select>'
        + '<input id="grade-score-'+savedIdx+'" type="text" placeholder="Score e.g. 72-68" style="background:var(--bg3);border:1px solid var(--border2);border-radius:5px;padding:3px 8px;color:var(--text);font-family:var(--font-mono);font-size:11px;width:130px" />'
        + '<button onclick="gradeBet('+savedIdx+')" style="background:var(--gold);color:#000;border:none;border-radius:5px;padding:4px 12px;font-family:var(--font-mono);font-size:11px;font-weight:700;cursor:pointer;width:100%">GRADE</button>'
        + '</div>';
    } else {
      resHtml = '<span class="badge gray">PENDING</span>';
    }

    var stChip = '';
    if(b.status && b.status !== 'PENDING') {
      var stColor = b.status==='IN PROGRESS'?'var(--gold)':b.status==='GRADED'?'var(--teal)':'var(--text3)';
      stChip = '<span style="font-size:9px;color:'+stColor+';font-family:var(--font-mono);margin-left:6px">'+b.status+'</span>';
    }

    var tr = document.createElement('tr');
    tr.innerHTML = '<td>'+(i+1)+'</td>'
      + '<td><div>'+( b.game||'')+'</div>'
      + (b.date?'<div style="font-size:10px;color:var(--text3)">'+b.date+'</div>':'')
      + stChip + '</td>'
      + '<td>'+( b.pick||'')+'</td>'
      + '<td class="right">'+( b.odds||'')+'</td>'
      + '<td class="right">'+( b.units||'')+'u</td>'
      + '<td class="right" style="color:var(--gold)">'+starsStr+'</td>'
      + '<td class="right '+plClass+'">'+plStr+'</td>'
      + '<td class="right">'+resHtml+'</td>';
    tbody.appendChild(tr);
  });
}'''

if idx != -1 and idx_end != -1:
    content = content[:idx] + new_tracker + content[idx_end:]
    print("renderTracker replaced with clean forEach version")
else:
    print("ERROR: Could not find renderTracker boundaries")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done! Size:", len(content))
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R - bet tracker should show all 62 bets!")
