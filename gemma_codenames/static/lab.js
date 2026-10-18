const $ = id => document.getElementById(id), V = window.VectorUI;
let report = null, stage = 0, pollTimer = null;
V.controls($('lab-config'));
fetch('/health').then(r => r.json()).then(r => {
    if (r.mode === 'demo') $('source').value = 'demo';
}).catch(() => {
});
$('new-seed').onclick = () => {
    $('seed').value = crypto.getRandomValues(new Uint32Array(1))[0];
};

function setRunning(running) {
    for (const e of $('experiment-form').elements) e.disabled = running;
    if (!running) {
        $('lab-config').querySelector('[data-config="precision"]').disabled = !$('lab-config').querySelector('[data-config="coefficients"]').checked;
    }
}

$('experiment-form').onsubmit = async e => {
    e.preventDefault();
    clearTimeout(pollTimer);
    setRunning(true);
    $('lab-error').hidden = true;
    $('lab-results').hidden = true;
    $('lab-progress').textContent = 'Starting experiment. Real-model loading may take time on the first run.';
    try {
        const response = await fetch('/api/lab', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                seed: Number($('seed').value),
                team: $('team').value,
                synthetic: $('source').value === 'demo', ...V.options($('lab-config'))
            })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid configuration.');
        poll(data.job_id);
    } catch (error) {
        fail(error.message);
    }
};

function fail(message) {
    $('lab-error').textContent = message;
    $('lab-error').hidden = false;
    $('lab-progress').textContent = '';
    setRunning(false);
}

async function poll(id) {
    try {
        const response = await fetch('/api/lab/' + encodeURIComponent(id));
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not read experiment.');
        $('lab-progress').textContent = data.stage;
        if (data.status === 'running') {
            pollTimer = setTimeout(() => poll(id), 600);
            return;
        }
        if (data.status === 'error') {
            fail(data.stage);
            return;
        }
        report = data.result;
        stage = 0;
        setRunning(false);
        $('lab-results').hidden = false;
        $('lab-demo').hidden = report.source !== 'demo';
        $('result-title').textContent = report.explanation;
        $('report-meta').textContent = `SEED ${report.seed} · ${report.team.toUpperCase()} TARGETS · ${report.model.model_id} · ${report.model.dimensions}D`;
        $('lab-board').style.gridTemplateColumns = `repeat(${Math.sqrt(report.board_size)},minmax(58px,1fr))`;
        $('lab-board').innerHTML = report.board.map(c => `<div class="card ${c.kind}"><span>${V.esc(c.word)}</span><small>${c.kind}</small></div>`).join('');
        renderStage();
    } catch (error) {
        fail(error.message);
    }
}

for (const button of document.querySelectorAll('[data-stage]')) button.onclick = () => {
    stage = Number(button.dataset.stage);
    renderStage();
};
$('next-stage').onclick = () => {
    stage = Math.min(2, stage + 1);
    renderStage();
};
$('download-report').onclick = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'}));
    const a = document.createElement('a');
    a.href = url;
    a.download = `vector-experiment-${report.seed}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function renderStage() {
    if (!report) return;
    const r = report.communication;
    document.querySelectorAll('[data-stage]').forEach(b => b.setAttribute('aria-selected', String(Number(b.dataset.stage) === stage)));
    $('next-stage').disabled = stage === 2;
    let html = '';
    if (stage === 0) {
        html = `<p class="eyebrow">SPYMASTER · FULL KEY</p><h2>Find an ideal separating direction</h2><div class="math-step"><code>max γ, subject to ‖q‖₂ ≤ 1<br>qᵀ(e(f) − e(u)) ≥ γ, for every friendly–danger pair</code><p>No minimum human association score. Only ranking and positive separation matter.</p></div><div class="metrics"><div class="metric"><b>${V.fmt(r.ideal.upper_bound)}</b><span>numerical upper bound</span></div><div class="metric"><b>${V.fmt(r.ideal.actual_gap)}</b><span>normalized ideal gap</span></div><div class="metric"><b>${r.friendly_count}</b><span>targets</span></div></div><p>${V.esc(r.ideal.note)}</p><p class="muted small">The unit ball admits the zero vector. A zero optimum does not supply a useful normalized direction. A positive ideal gap still does not guarantee that the allowed words can encode it.</p>`;
    }
    if (stage === 1) {
        html = `<p class="eyebrow">ENCODER · WORD SEARCH</p><h2>Approximate the direction using words</h2><p class="small">${V.esc(V.summary(r.config))}</p>${V.reportHTML(r)}<h3 class="small">Exactly what crosses the wire</h3><pre>${V.esc(JSON.stringify(r.message, null, 2))}</pre><p class="muted small">Words, coefficients, guess count and model identity. No target list, hidden colors, ideal vector or precomputed board scores.</p>`;
    }
    if (stage === 2) {
        html = `<p class="eyebrow">RECEIVER · PUBLIC BOARD ONLY</p><h2>Decode, rank, and guess</h2><div class="math-step"><code>p = Σ αᵢe(wᵢ)<br>q̂ = p / ‖p‖₂<br>score(board word) = q̂ᵀe(word)</code></div><p class="wire-message">${V.esc(V.label(r.message))}</p><div class="metrics"><div class="metric"><b>${V.fmt(r.decoded_gap)}</b><span>all-target gap</span></div><div class="metric"><b>${V.fmt(r.ideal_alignment)}</b><span>cosine to ideal</span></div><div class="metric"><b>${r.decoded_coverage}/${r.friendly_count}</b><span>targets above danger</span></div></div><p>Encoding/decoding reconstruction error: <b>${V.fmt(r.reconstruction_error, 10)}</b>. Distance to the ideal vector: ${V.fmt(r.ideal_distance)}. The first measures protocol consistency; the second measures lossy encoding.</p><h3 class="small">Simulated guesses · stops at count or first mistake</h3><ol>${r.simulation.map(g => `<li class="${g.kind === 'red' ? 'red-text' : g.kind === 'blue' ? 'blue-text' : ''}">${V.esc(g.word)} · ${V.fmt(g.similarity)} · ${g.correct ? 'correct' : 'wrong — turn stops'}</li>`).join('')}</ol><h3 class="small">Full decoded ranking (key shown by evaluator)</h3><div class="table-scroll"><table><thead><tr><th>Word</th><th>Role</th><th>Cosine</th></tr></thead><tbody>${report.best.rankings.map(row => `<tr><td>${V.esc(row.word.toUpperCase())}</td><td>${row.kind}</td><td>${V.fmt(row.similarity)}</td></tr>`).join('')}</tbody></table></div>`;
    }
    $('stage-content').innerHTML = html;
    const plot = stage === 0 ? {
        ...r.plot,
        points: r.plot.points.filter(p => ['word', 'ideal'].includes(p.type)),
        contributions: []
    } : r.plot;
    $('lab-map-note').textContent = `${plot.dimensions}D → 2D · ${(plot.variance * 100).toFixed(1)}% board variance retained. ${plot.note}`;
    V.plot($('lab-map'), plot, report.board, Object.fromEntries(report.best.rankings.map(row => [row.word.toUpperCase(), row.similarity])));
}
