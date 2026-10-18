/* Rendering and input only. Game authority and all vector math live in Python. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
}[c]));
const fmt = (n, digits = 3) => Number.isFinite(n) ? n.toFixed(digits) : '—';
let room, ws, selected = null, activeTab = 'scores', historyTurn = 'live', retries = 0, reconnectTimer;
let selectedPoint = null, connected = false, inflight = false;
const V = window.VectorUI;
V.controls($('home-config'));
let configInitialized = false;
$('room-config-form').onsubmit = e => {
    e.preventDefault();
    command({type: 'configure', ...V.options($('room-config'))});
};

function notice(message = '') {
    $('notice').textContent = message;
    $('notice').hidden = !message;
}

function command(action) {
    if (!connected || inflight || !room) return;
    inflight = true;
    notice();
    const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
    ws.send(JSON.stringify({actionId: id, version: room.version, action}));
    renderControls();
}

function button(text, action, disabled = false, primary = false) {
    const b = document.createElement('button');
    b.textContent = text;
    b.disabled = disabled || !connected || inflight || room?.pending;
    if (primary) b.className = 'primary';
    b.onclick = () => command(action);
    return b;
}

function connect(code) {
    clearTimeout(reconnectTimer);
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/${code}`);
    ws.onopen = () => {
        connected = true;
        inflight = false;
        retries = 0;
        $('connection').textContent = 'CONNECTED';
        notice();
        if (room) render();
    };
    ws.onmessage = event => {
        const data = JSON.parse(event.data);
        if (data.type === 'error') {
            inflight = false;
            notice(data.message);
        }
        if (data.type === 'state') {
            room = data.room;
            inflight = false;
            render();
        }
    };
    ws.onclose = event => {
        connected = false;
        inflight = false;
        $('connection').textContent = 'DISCONNECTED';
        if (room) renderControls();
        if (event.code === 1008) {
            notice('Room not found or access denied. Return home and check the invite code.');
            return;
        }
        notice('Connection lost. Reconnecting; your seat will be restored.');
        reconnectTimer = setTimeout(() => connect(code), Math.min(1000 * 2 ** retries++, 15000));
    };
}

$('create-form').onsubmit = async e => {
    e.preventDefault();
    const b = e.submitter;
    b.disabled = true;
    try {
        const response = await fetch('/api/rooms', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...V.options($('home-config'))})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail);
        location.assign(result.url);
    } catch (error) {
        notice(error.message);
        b.disabled = false;
    }
};
$('join-form').onsubmit = e => {
    e.preventDefault();
    location.assign('/room/' + $('join-code').value.trim().toUpperCase());
};
$('copy-link').onclick = async () => {
    try {
        await navigator.clipboard.writeText(location.href);
        $('copy-link').textContent = 'Copied';
    } catch {
        notice('Invite link: ' + location.href);
    }
};
$('clue-form').onsubmit = e => {
    e.preventDefault();
    command({type: 'clue', word: $('clue-word').value.trim(), count: Number($('clue-count').value)});
};
$('history').onchange = e => {
    historyTurn = e.target.value;
    selectedPoint = null;
    renderAnalysis();
};
for (const tab of document.querySelectorAll('[data-tab]')) tab.onclick = () => {
    activeTab = tab.dataset.tab;
    document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b === tab)));
    for (const name of ['scores', 'search']) $(name + '-view').hidden = name !== activeTab;
    renderAnalysis();
};

function render() {
    $('home').hidden = true;
    $('room').hidden = false;
    $('lobby').classList.toggle('in-game', room.phase !== 'lobby');
    $('room-code').textContent = `ROOM ${room.code} · TURN ${room.turnNumber}`;
    $('status').textContent = room.phase === 'lobby' ? 'Make a connection.' : room.phase === 'finished' ? `${room.winner.toUpperCase()} wins.` : `${room.turn.toUpperCase()} ${room.phase === 'clue' ? 'is finding a clue.' : 'is guessing.'}`;
    $('mode').textContent = room.botMode === 'demo' ? 'Synthetic demo' : 'EmbeddingGemma';
    $('demo-notice').hidden = room.botMode !== 'demo';
    $('red-count').textContent = `RED · ${room.remaining.red}`;
    $('blue-count').textContent = `BLUE · ${room.remaining.blue}`;
    $('role-label').textContent = (room.yourSeat || (room.spectator ? 'ANALYSIS SPECTATOR' : 'PUBLIC SPECTATOR')).replace('-', ' / ').toUpperCase();
    $('clue').textContent = room.clue ? `${room.clue.message ? V.label(room.clue.message) : V.displayClue(room.clue.word.toUpperCase())} · ${room.clue.count}` : '—';
    $('turn-info').textContent = room.phase === 'guess' ? `${room.guessesLeft} guesses available` : room.phase === 'finished' ? room.winReason : '';
    $('progress').textContent = room.botError || room.stage || (room.paused ? 'Paused · advance one decision at a time.' : '');
    renderSeats();
    renderBoard();
    renderControls();
    $('events').replaceChildren(...room.events.slice().reverse().map(e => {
        const li = document.createElement('li');
        li.textContent = V.displayClue(e.text);
        return li;
    }));
    const old = historyTurn;
    $('history').innerHTML = `<option value="live">${!room.clue && room.history.length ? 'Latest completed clue' : 'Current turn'}</option>` + room.history.map(d => `<option value="${d.turn}">Turn ${d.turn} · ${esc(d.clue.message ? V.label(d.clue.message) : V.displayClue(d.clue.word))} · ${d.clue.count}</option>`).join('');
    historyTurn = room.history.some(d => String(d.turn) === old) ? old : 'live';
    $('history').value = historyTurn;
    renderLiveSearch();
    $('model-analysis').hidden = !room.canSeeAnalysis;
    $('model-analysis').closest('.layout').classList.toggle('player-layout', !room.canSeeAnalysis);
    if (room.canSeeAnalysis) renderAnalysis();
}

function renderSeats() {
    $('room-config-summary').textContent = V.summary({
        ...{
            max_words: 3,
            coefficients: false,
            target_gap: .001
        }, ...room.communication, board_size: room.board_size
    });
    $('room-config-editor').hidden = !(room.isHost && room.phase === 'lobby');
    if (!configInitialized) {
        V.controls($('room-config'), {...room.communication, board_size: room.board_size});
        configInitialized = true;
    }
    for (const control of $('room-config-form').elements) control.disabled = room.pending || inflight || !connected;
    $('room-config').querySelector('[data-config=precision]').disabled = !$('room-config').querySelector('[data-config=coefficients]').checked;
    $('lobby').querySelector('h2').textContent = room.phase === 'lobby' ? 'Take a seat' : 'Four seats';
    $('player-name').hidden = room.phase !== 'lobby';
    $('seats').replaceChildren();
    for (const seat of room.seats) {
        const div = document.createElement('div');
        div.className = 'seat';
        div.innerHTML = `<b class="${seat.team}-text">${esc(seat.id.replace('-', ' / '))}</b><p>${esc(seat.name || 'Bot')}${seat.isYou ? ' · you' : ''} · ${seat.controller === 'bot' ? 'automated' : seat.online ? 'online' : 'offline'}${room.phase === 'lobby' && seat.controller === 'human' ? (seat.ready ? ' · ready' : ' · not ready') : ''}</p>`;
        if (room.phase === 'lobby' && !room.spectator) {
            div.append(button('Play', {
                type: 'claim',
                slotId: seat.id,
                controller: 'human',
                name: $('player-name').value || 'Guest'
            }, seat.occupied && !seat.isYou));
            div.append(button('Watch bot', {
                type: 'claim',
                slotId: seat.id,
                controller: 'bot',
                name: $('player-name').value || 'Guest'
            }, seat.occupied && !seat.isYou));
        }
        if (room.isHost && room.phase !== 'finished' && seat.controller === 'human' && !seat.online) {
            div.append(button('Use bot', {type: 'replace', slotId: seat.id}));
        }
        $('seats').append(div);
    }
    const area = $('lobby-actions');
    area.replaceChildren();
    if (!room.yourSeat && !room.spectator && room.phase !== 'finished') area.append(button('Analysis spectator', {type: 'spectate'}));
    if (room.phase === 'lobby') {
        const yours = room.seats.find(s => s.isYou);
        if (yours) {
            area.append(button('Leave seat', {type: 'leave'}));
            if (yours.controller === 'human') area.append(button(yours.ready ? 'Not ready' : 'Ready', {type: 'ready'}));
        }
        if (room.isHost) area.append(button('Start game', {type: 'start'}, !room.canStart, true));
    }
}

function renderBoard() {
    const canGuess = room.phase === 'guess' && room.activeSlot === room.yourSeat && room.seats.find(s => s.isYou)?.controller === 'human';
    if (selected && !room.board.some(c => c.id === selected && !c.revealed)) selected = null;
    $('board').style.gridTemplateColumns = `repeat(${Math.sqrt(room.board_size)},minmax(58px,1fr))`;
    $('board').replaceChildren(...room.board.map(card => {
        const b = document.createElement('button');
        b.className = `card ${card.kind || ''} ${card.revealed ? 'revealed' : ''} ${selected === card.id ? 'selected' : ''}`;
        const word = document.createElement('span');
        word.textContent = card.word;
        b.append(word);
        const score = document.createElement('small');
        score.textContent = card.revealed ? 'REVEALED' : Number.isFinite(card.score) ? fmt(card.score) : '';
        b.append(score);
        b.disabled = !canGuess || card.revealed || room.pending || inflight || !connected;
        b.setAttribute('aria-label', `${card.word}${card.kind ? ', ' + card.kind : ''}${card.revealed ? ', revealed' : ''}${Number.isFinite(card.score) ? ', cosine ' + fmt(card.score) : ''}`);
        b.onclick = () => {
            selected = selected === card.id ? null : card.id;
            renderBoard();
            renderControls();
        };
        return b;
    }));
}

function renderControls() {
    if (!room) return;
    const area = $('controls');
    area.replaceChildren();
    const yours = room.seats.find(s => s.isYou);
    const yourTurn = room.yourSeat === room.activeSlot && yours?.controller === 'human';
    $('clue-form').hidden = !(yourTurn && room.phase === 'clue');
    for (const control of $('clue-form').elements) control.disabled = room.pending || inflight || !connected;
    $('clue-count').max = room.remaining[room.turn];
    if (yourTurn && room.phase === 'guess') {
        area.append(button(selected ? `Guess ${room.board.find(c => c.id === selected).word}` : 'Select a word', {
            type: 'guess',
            cardId: selected
        }, !selected, true));
        area.append(button('End turn', {type: 'end-turn'}, room.guesses === 0));
    }
    if (room.isHost && room.allBots && ['clue', 'guess'].includes(room.phase)) {
        area.append(button(room.paused ? 'Play automatically' : 'Pause', {type: 'pause'}));
        if (room.paused) area.append(button('Next decision →', {type: 'step'}, false, true));
    }
    if (room.isHost && room.botError) area.append(button('Retry model', {type: 'retry'}));
    if (room.isHost && room.phase === 'finished') area.append(button('New board', {type: 'rematch'}, false, true));
}

function currentAnalysis() {
    if (historyTurn === 'live' && room.clue) return {
        clue: room.clue,
        analysis: room.analysis,
        plot: room.plot,
        scores: Object.fromEntries(room.board.map(c => [c.id, c.score]))
    };
    const d = (historyTurn === 'live' ? room.history.at(-1) : room.history.find(d => String(d.turn) === historyTurn))?.clue;
    return {clue: d, analysis: d?.analysis, plot: d?.plot, scores: d?.scores || {}};
}

function renderAnalysis() {
    if (!room) return;
    const {clue, analysis, plot, scores} = currentAnalysis();
    $('analysis-context').textContent = historyTurn === 'live' && !room.clue && clue ? 'Showing the latest completed clue. Live search above is for the next clue.' : historyTurn !== 'live' ? `Inspecting turn ${historyTurn}. Live search, if shown, is for the current turn.` : '';
    $('wire-summary').textContent = clue?.message ? V.label(clue.message) : '';
    const rows = room.board.filter(c => Number.isFinite(scores[c.id])).map(c => ({
        ...c,
        score: scores[c.id]
    })).sort((a, b) => b.score - a.score);
    $('pipeline').querySelectorAll('span').forEach((s, i) => {
        s.classList.toggle('active', !!clue || (!!room.stage && i === (room.stage.includes('Encoding') ? 0 : room.stage.includes('Computing') ? 2 : 3)));
    });
    $('metrics').innerHTML = analysis ? [
        [analysis.targets?.length || clue?.count || '—', 'targets'], [fmt(analysis.safetySlack), 'safety slack'], [analysis.legalCandidates?.toLocaleString() || '—', 'legal clues']
    ].map(([value, label]) => `<div class="metric"><b>${esc(value)}</b><span>${label}</span></div>`).join('') : `<div class="metric"><b>${rows.length ? rows.length : '—'}</b><span>word scores</span></div><div class="metric"><b>${plot?.dimensions || '—'}</b><span>dimensions</span></div><div class="metric"><b>${clue?.count || '—'}</b><span>clue count</span></div>`;
    $('score-note').textContent = !clue ? 'Start a game and advance the first clue to see the real scoring pipeline.' : analysis ? `${analysis.fallback ? 'FALLBACK · No candidate meets the thresholds. ' : ''}${analysis.summary} Orange tick: required threshold.` : 'Public cosine scores. Targets and danger margins are visible to analysis spectators.';
    $('rankings').innerHTML = rows.length ? rows.map(c => {
        const width = Math.abs(c.score) * 50, left = c.score < 0 ? 50 - width : 50;
        const threshold = Number.isFinite(analysis?.requiredThreshold) ? `<i class="threshold" style="left:${(analysis.requiredThreshold + 1) * 50}%"></i>` : '';
        const isTarget = analysis?.targets?.includes(c.word);
        return `<div class="ranking ${selectedPoint === c.word ? 'active' : ''}" data-word="${esc(c.word)}" tabindex="0" role="button" aria-label="Inspect ${esc(c.word)}"><span>${esc(c.word)}${isTarget ? ' *' : ''}</span><div class="track"><i class="bar ${c.kind || ''}" style="left:${left}%;width:${width}%"></i>${threshold}</div><strong>${fmt(c.score)}</strong></div>`;
    }).join('') : '<p class="empty">Every connection starts with a vector.<br>Scores will appear after the first clue.</p>';
    for (const el of $('rankings').querySelectorAll('[data-word]')) {
        el.onclick = () => {
            selectedPoint = el.dataset.word;
            renderAnalysis();
        };
        el.onkeydown = e => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                el.click();
            }
        };
    }
    renderMap(analysis?.communication?.plot || plot, scores);
    renderSearch(analysis, clue);
}

function renderMap(plot, scores) {
    $('map-note').textContent = plot ? `${plot.dimensions}D → 2D · ${(plot.variance * 100).toFixed(1)}% variance retained. Cosine scores use the full embedding.` : '';
    V.plot($('embedding-map'), plot, room.board,
        Object.fromEntries(room.board.map(c => [c.word, scores[c.id]])), {
            selected: selectedPoint,
            onSelect: word => { selectedPoint = word; renderAnalysis(); }
        });
}

function renderSearch(a, clue) {
    if (!a) {
        $('search-results').innerHTML = '<p class="empty">The clue search uses the hidden key.<br>Choose Analysis spectator to inspect it. Full results appear when the first clue is ready; live search is shown above while it runs.</p>';
        return;
    }
    let html = `<p class="small">${esc(a.summary)}</p>`;
    if (a.communication) html += V.reportHTML(a.communication);
    if (a.matrixShape) html += `<p class="muted small">${a.matrixShape[0].toLocaleString()} candidates × ${a.matrixShape[1]} board words · ${fmt(a.elapsed, 2)} s · ${esc(a.model?.model_id)} · ${a.model?.dimensions}D</p>`;
    if (a.weakestTarget) html += `<table><tbody><tr><th>Weakest target</th><td>${esc(a.weakestTarget.word)}</td><td>${fmt(a.weakestTarget.score)}</td></tr><tr><th>Limiting danger</th><td>${esc(a.limitingDanger?.word)}</td><td>${fmt(a.limitingDanger?.score)}</td></tr><tr><th>Required threshold</th><td></td><td>${fmt(a.requiredThreshold)}</td></tr><tr><th>Safety slack</th><td></td><td>${fmt(a.safetySlack)}</td></tr></tbody></table>`;
    if (a.config?.min_similarity !== undefined) html += `<p class="muted small">Floor ${a.config.min_similarity} · neutral gap ${a.config.neutral_margin} · opponent ${a.config.opponent_margin} · assassin ${a.config.assassin_margin}</p>`;
    if (a.coverageChecks?.length) {
        html += '<h3 class="small">Could a clue cover more words?</h3><div class="coverage">' + a.coverageChecks.map(c => `<div class="${c.feasible ? 'pass' : ''}" title="Best candidate: ${esc(c.best_candidate)}"><b>${c.count}</b>${c.feasible ? 'qualifies' : 'fails'}<br>${fmt(c.best_constraint_slack)}</div>`).join('') + '</div><p class="muted small">Each cell is the best constraint slack across all legal clues for that count. Negative means none qualifies.</p>';
    }

    if (a.geometry) {
        const g = a.geometry;
        html += `<div class="experiment"><h3>Ideal direction · ${esc(g.status)}</h3>${g.upper_bound !== undefined ? `<code>γ* ≈ ${fmt(g.upper_bound, 4)}</code><p>Numerical unit-ball bound on all-target separation.</p>` : ''}<p>${esc(g.note)}</p>${g.nearest ? '<p>Nearest vocabulary words (may be illegal clues): ' + g.nearest.map(n => `${esc(n.word)} (${fmt(n.similarity)})`).join(', ') + '</p>' : ''}</div>`;
    }
    $('search-results').innerHTML = html;
}

const match = location.pathname.match(/^\/room\/([a-zA-Z]{1,60})\/?$/);
if (match) {
    $('home').hidden = true;
    $('room').hidden = false;
    connect(match[1].toUpperCase());
}

function renderLiveSearch() {
    const root = $('live-search'), s = room.liveSearch;
    root.hidden = !(room.pending && s && room.canSeeAnalysis && room.spectator);
    if (root.hidden) {
        root.replaceChildren();
        return;
    }
    const label = c => V.label({
        weighted: !!c.coefficients, precision: room.communication.precision,
        components: c.words.map((word, i) => ({word, coefficient: c.coefficients?.[i] ?? 1}))
    });
    root.innerHTML = `<div class="experiment"><h3>LIVE SEARCH · up to ${s.depth} words</h3>
    <p>${s.evaluations.toLocaleString()} evaluations · ${fmt(s.elapsed, 1)}s elapsed</p>
    <p>Best so far: <b>${esc(label(s.best))}</b></p>
    <p>${s.best.coverage}/${s.friendly_count} targets · all-target gap ${fmt(s.best.full_gap, 4)} · required ${fmt(s.target_gap, 4)}</p>
    ${s.candidate ? `<p class="muted small">Latest sampled candidate: ${esc(label(s.candidate))} · ${s.candidate.coverage}/${s.friendly_count} targets · gap ${fmt(s.candidate.full_gap, 4)}</p>` : ''}
    <div class="table-scroll"><table><thead><tr><th>Depth</th><th>Evaluated</th><th>Best coverage</th><th>Gap</th></tr></thead><tbody>${s.trace.slice(-8).map(t => `<tr><td>${t.depth}</td><td>${t.evaluations}</td><td>${t.coverage}/${s.friendly_count}</td><td>${fmt(t.gap, 4)}</td></tr>`).join('')}</tbody></table></div>
    <p class="muted small">Sampled updates, up to twice per second plus depth boundaries. Best-so-far messages are provisional.</p></div>`;
}
