/* Shared configuration and mathematical diagnostics for rooms and the laboratory. */
window.VectorUI = (() => {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
    const fmt = (n, d = 4) => Number.isFinite(n) ? n.toFixed(d) : '—';
    const defaults = {
        common_words_only: true,
        board_size: 25,
        max_words: 1,
        coefficients: false,
        precision: 2,
        target_gap: .005,
        beam_width: 8,
        shortlist: 32,
        max_evaluations: 2000,
        time_limit: 5,
        stop_at_one_shot: true
    };
    // Screenshots in the supplied order; board size is intentionally not a preset field.
    const presets = {
        human: {
            common_words_only: true,
            max_words: 1,
            target_gap: .01,
            coefficients: false,
            precision: 2,
            stop_at_one_shot: true,
            time_limit: 10,
            max_evaluations: 2000,
            beam_width: 16,
            shortlist: 64
        },
        hard: {
            common_words_only: true,
            max_words: 1,
            target_gap: .0075,
            coefficients: false,
            precision: 2,
            stop_at_one_shot: true,
            time_limit: 10,
            max_evaluations: 4000,
            beam_width: 16,
            shortlist: 64
        },
        verbose: {
            common_words_only: false,
            max_words: 1,
            target_gap: .001,
            coefficients: false,
            precision: 2,
            stop_at_one_shot: true,
            time_limit: 10,
            max_evaluations: 4000,
            beam_width: 16,
            shortlist: 64
        },
        insane: {
            common_words_only: false,
            max_words: 1,
            target_gap: .0001,
            coefficients: false,
            precision: 2,
            stop_at_one_shot: true,
            time_limit: 20,
            max_evaluations: 4000,
            beam_width: 16,
            shortlist: 64
        },
        god: {
            common_words_only: false,
            max_words: 2,
            target_gap: .00001,
            coefficients: false,
            precision: 2,
            stop_at_one_shot: true,
            time_limit: 20,
            max_evaluations: 8000,
            beam_width: 32,
            shortlist: 128
        }
    };

    function presetName(config) {
        return Object.keys(presets).find(name => Object.entries(presets[name]).every(([key, value]) => config[key] === value)) || 'custom';
    }

    const joinWords = words => words.join(' ');
    const displayClue = text => String(text ?? '').replaceAll(' + ', ' ');

    function controls(root, initial = {}) {
        const config = {...defaults, ...initial};
        const num = (name, label, min, max, step = 1) => `<label>${label}<input data-config="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${config[name]}" required></label>`;
        root.innerHTML = `<fieldset class="board-settings"><legend>Board size</legend><label>Board side (N × N)<input data-board-size type="number" min="2" max="10" step="1" value="${Math.sqrt(config.board_size)}" required></label></fieldset>
        <fieldset class="preset-picker"><legend>Bot preset <span data-preset-status class="small muted"></span></legend><div class="preset-buttons">${Object.keys(presets).map(name => `<button type="button" data-preset="${name}" aria-pressed="false">${name[0].toUpperCase() + name.slice(1)}</button>`).join('')}</div></fieldset>
        <div class="config-grid">${num('max_words', 'Maximum words', 1, 12)}${num('target_gap', 'Required gap', .000001, 1, .000001)}${num('precision', 'Coefficient decimals', 0, 4)}</div>
        <div class="config-grid checkbox-settings"><label class="checkbox"><input type="checkbox" data-config="coefficients" ${config.coefficients ? 'checked' : ''}> Allow coefficients</label><label class="checkbox"><input type="checkbox" data-config="common_words_only" ${config.common_words_only ? 'checked' : ''}> Common clue words only</label></div>
        <details><summary>Search budget</summary><div class="config-grid">${num('time_limit', 'Combination search seconds', .1, 60, .1)}${num('max_evaluations', 'Maximum combinations', 1, 20000)}${num('beam_width', 'Beam width', 1, 32)}${num('shortlist', 'Candidate shortlist', 4, 128)}</div><p class="muted small">Model loading, encoding and the ideal solve occur before the bounded combination search. Search is approximate; a larger budget may find a better message.</p></details>`;
        const toggle = () => root.querySelector('[data-config="precision"]').disabled = !root.querySelector('[data-config="coefficients"]').checked;
        const buttons = root.querySelectorAll('[data-preset]');
        const sync = () => {
            toggle();
            const selected = presetName(read(root));
            for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.preset === selected));
            root.querySelector('[data-preset-status]').textContent = selected === 'custom' ? '· Custom settings' : '';
        };
        for (const button of buttons) button.onclick = () => {
            const preset = presets[button.dataset.preset];
            if (!preset) return;
            for (const input of root.querySelectorAll('[data-config]')) {
                if (input.type === 'checkbox') input.checked = preset[input.dataset.config];
                else input.value = preset[input.dataset.config];
            }
            sync();
        };
        for (const input of root.querySelectorAll('[data-config]')) input.addEventListener('input', sync);
        sync();
    }

    function read(root) {
        return {...Object.fromEntries([...root.querySelectorAll('[data-config]')].map(e => [e.dataset.config, e.type === 'checkbox' ? e.checked : Number(e.value)])), stop_at_one_shot: true};
    }

    function options(root) {
        return {board_size: Number(root.querySelector('[data-board-size]').value) ** 2, communication: read(root)};
    }

    function label(message) {
        if (!message) return '';
        return joinWords(message.components.map(c => `${c.word}${message.weighted ? ' × ' + c.coefficient.toFixed(message.precision) : ''}`));
    }

    function summary(config) {
        return `${config.board_size ? Math.sqrt(config.board_size) + ' × ' + Math.sqrt(config.board_size) + ' · ' : ''}${config.common_words_only ? 'Common clues' : 'All clues'} · Up to ${config.max_words} words · ${config.coefficients ? 'coefficients, ' + config.precision + ' decimals' : 'equal weights'} · gap ≥ ${config.target_gap}`;
    }

    function trace(report) {
        const rows = report.trace || [];
        if (!rows.length) return '';
        const all = rows.map(r => r.best_one_shot_gap), floor = report.config.target_gap;
        const min = Math.min(0, ...all), max = Math.max(floor + .02, ...all), range = Math.max(.01, max - min);
        const x = i => 45 + i * 360 / Math.max(1, rows.length - 1), y = v => 145 - (v - min) / range * 115;
        const path = all.map((v, i) => `${i ? 'L' : 'M'}${x(i)} ${y(v)}`).join(' ');
        return `<svg class="trace-chart" viewBox="0 0 450 185" role="img" aria-label="Best evaluated all-target separation versus word budget"><path d="M40 ${y(floor)}H420" stroke="#985314" stroke-dasharray="4 3"/><text x="42" y="${y(floor) - 6}">one-shot gap ${floor}</text><path d="${path}" fill="none" stroke="#59409a" stroke-width="2"/>${rows.map((r, i) => `<circle cx="${x(i)}" cy="${y(all[i])}" r="4" fill="#59409a"><title>Up to ${r.depth} words: ${fmt(all[i])}</title></circle><text x="${x(i) - 4}" y="166">${r.depth}</text>`).join('')}<text x="140" y="182">Maximum words searched</text><text x="5" y="20">${fmt(max, 2)}</text><text x="5" y="146">${fmt(min, 2)}</text></svg>`;
    }

    function reportHTML(r) {
        if (!r) return '';
        return `<div class="experiment"><h3>${r.one_shot ? 'ONE-SHOT VERIFIED' : 'PARTIAL ENCODING'} · ${r.best.word_count} words</h3><p class="wire-message">${esc(label(r.message))}</p><p>Decoded all-target gap <b>${fmt(r.decoded_gap)}</b> · ${r.decoded_coverage}/${r.friendly_count} targets qualify</p><p>Ideal-vector alignment ${fmt(r.ideal_alignment)} · reconstruction error ${fmt(r.reconstruction_error, 8)}</p><p>${esc(r.stop_reason)} · ${r.evaluations.toLocaleString()} evaluations · ${r.packet_bytes} transmitted JSON bytes</p></div>${trace(r)}<div class="table-scroll"><table><thead><tr><th>Budget</th><th>Best retained message</th><th>Coverage</th><th>All-target gap</th></tr></thead><tbody>${r.trace.map(t => `<tr><td>≤ ${t.depth}</td><td>${esc(joinWords(t.best.words))}</td><td>${t.best.coverage}</td><td>${fmt(t.best.full_gap)}</td></tr>`).join('')}</tbody></table></div><p class="muted small">${esc(r.optimality)} The chart shows the best all-target gap evaluated; the table shows the retained coverage-first winner. Coefficient LPs optimize an unnormalized margin, then rounding and full cosine scoring decide the result.</p>`;
    }

    const mapStates = new WeakMap();
    function plot(root, data, board = [], scores = {}, options = {}) {
        mapStates.get(root)?.observer?.disconnect();
        if (!data?.points?.length) {
            root.innerHTML = '<p class="empty">Waiting for embeddings.</p>';
            mapStates.delete(root);
            return;
        }
        const signature = JSON.stringify(data.points);
        let state = mapStates.get(root);
        if (!state || state.signature !== signature) {
            state = {signature, zoom: 1, x: 0, y: 0, selected: null, query: ''};
            mapStates.set(root, state);
        }
        if (options.selected !== undefined) state.selected = options.selected;
        const points = data.points;
        const palette = {red:'#9c4038',blue:'#286380',neutral:'#81704c',assassin:'#292438',word:'#857792',component:'#985314',decoded:'#16716c',ideal:'#59409a',clue:'#685288'};
        const bounds = [...points, {x:0,y:0}];
        const xs = bounds.map(p=>p.x), ys = bounds.map(p=>p.y);
        const cx = (Math.min(...xs)+Math.max(...xs))/2, cy = (Math.min(...ys)+Math.max(...ys))/2;
        const scale = Math.min(420/Math.max(.001,Math.max(...xs)-Math.min(...xs)), 300/Math.max(.001,Math.max(...ys)-Math.min(...ys)));
        const base = (x,y) => [(x-cx)*scale, -(y-cy)*scale];
        const xy = (x,y) => {const b=base(x,y); return [280+state.x+b[0]*state.zoom,200+state.y+b[1]*state.zoom];};
        root.innerHTML = `<div class="map-tools"><input type="search" aria-label="Find a word in the embedding map" placeholder="Find a word" value="${esc(state.query)}"><button type="button" data-map="find">Find</button><button type="button" data-map="out" aria-label="Zoom out">−</button><button type="button" data-map="in" aria-label="Zoom in">+</button><button type="button" data-map="reset">Reset</button></div><svg class="interactive-map" viewBox="0 0 560 400" tabindex="0" role="group" aria-label="Embedding map: drag to pan, scroll or pinch to zoom"><g class="map-content"></g></svg><p class="plot-detail small" aria-live="polite"></p>`;
        const svg = root.querySelector('svg'), content = root.querySelector('.map-content'), detail = root.querySelector('.plot-detail');
        let hovered = null;
        function describe(p) {
            const score = scores[p.word.toUpperCase()];
            return `${p.word} · ${p.type}${Number.isFinite(score)?' · cosine '+fmt(score):''}${p.coefficient!==undefined?' · weight '+p.coefficient:''}`;
        }
        function draw() {
            const origin=xy(0,0);
            let html=`<path d="M0 ${origin[1]}H560M${origin[0]} 0V400" stroke="#d6d0df" stroke-dasharray="3 5"/>`;
            for (const c of data.contributions || []) {
                const a=xy(...c.from),b=xy(...c.to);
                html+=`<path d="M${a[0]} ${a[1]}L${b[0]} ${b[1]}" stroke="#a295b5" stroke-width="1.5"/>`;
            }
            const labels=[];
            const fontSize = 11 * 560 / (svg.clientWidth || 560);
            // Keep selected, hovered and clue labels ahead of background labels.
            const order=[...points.entries()].sort((a,b)=>priority(b[1])-priority(a[1]));
            function priority(p){return (p.word===state.selected?4:0)+(p.word===hovered?2:0)+(p.type!=='word'?1:0);}
            for (const [i,p] of order) {
                const [x,y]=xy(p.x,p.y), card=board.find(c=>c.word.toUpperCase()===p.word.toUpperCase());
                const color=p.type==='word'?(palette[card?.kind]||palette.word):(palette[p.type]||palette.component);
                const active=p.word===state.selected, hover=p.word===hovered;
                if (['decoded','ideal'].includes(p.type)) html+=`<path d="M${origin[0]} ${origin[1]}L${x} ${y}" stroke="${color}" stroke-width="1.5" ${p.type==='ideal'?'stroke-dasharray="5 4"':''}/>`;
                if(x < -20 || x > 580 || y < -20 || y > 420)continue;
                const w=p.word.length*fontSize*.6+8;
                let label='';
                for(const [dx,dy] of [[10,-8],[10,17],[-w-7,-8],[-w-7,17]]) {
                    const r={x:x+dx,y:y+dy-fontSize,w,h:fontSize+4};
                    if (r.x<0 || r.x+w>560 || r.y<0 || r.y+r.h>400)continue;
                    if(labels.some(a=>r.x<a.x+a.w&&r.x+r.w>a.x&&r.y<a.y+a.h&&r.y+r.h>a.y))continue;
                    labels.push(r);label=`<text x="${r.x+3}" y="${r.y+fontSize}" style="font-size:${fontSize}px" fill="${color}" font-weight="${active||hover?700:400}">${esc(p.word)}</text>`;break;
                }
                html+=`<g data-point="${i}" role="button" tabindex="0" aria-label="${esc(describe(p))}" aria-pressed="${active}"><title>${esc(describe(p))}</title><circle cx="${x}" cy="${y}" r="12" fill="transparent"/><circle cx="${x}" cy="${y}" r="${active||hover?7:p.type==='word'?4:6}" fill="${color}" ${active?'stroke="'+color+'" stroke-width="7" stroke-opacity=".2"':''}/>${label}</g>`;
            }
            content.innerHTML=html;
            const p=points.find(p=>p.word===(hovered||state.selected));
            detail.textContent=p?describe(p):'Drag to pan · scroll or pinch to zoom · select a word';
        }
        function select(word, focus=false) {
            state.selected=word;
            if(focus){const p=points.find(p=>p.word===word),b=base(p.x,p.y);state.zoom=Math.max(1.8,state.zoom);state.x=-b[0]*state.zoom;state.y=-b[1]*state.zoom;}
            draw();options.onSelect?.(word);
        }
        function local(e){const r=svg.getBoundingClientRect();return {x:(e.clientX-r.left)*560/r.width,y:(e.clientY-r.top)*400/r.height};}
        function zoom(factor, at={x:280,y:200}) {
            const next=Math.max(.4,Math.min(16,state.zoom*factor)),ratio=next/state.zoom;
            state.x=(state.x+280-at.x)*ratio+at.x-280;
            state.y=(state.y+200-at.y)*ratio+at.y-200;
            state.zoom=next;draw();
        }
        svg.onwheel=e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.0015),local(e));};
        const pointers=new Map();let moved=false,pressed=null;
        svg.onpointerdown=e=>{
            if(e.button!==0)return;
            pointers.set(e.pointerId,local(e));moved=false;
            pressed=e.target.closest('[data-point]')?.dataset.point;
            svg.setPointerCapture(e.pointerId);svg.classList.add('dragging');
        };
        svg.onpointermove=e=>{
            if(!pointers.has(e.pointerId)){
                const index=e.target.closest('[data-point]')?.dataset.point;
                const next=index===undefined?null:points[index].word;
                if(next!==hovered){hovered=next;draw();}return;
            }
            const previous=pointers.get(e.pointerId),next=local(e);
            const before=[...pointers.values()];pointers.set(e.pointerId,next);
            if(pointers.size===2){
                const after=[...pointers.values()];
                const distance=a=>Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);
                const center=a=>({x:(a[0].x+a[1].x)/2,y:(a[0].y+a[1].y)/2});
                const a=center(before),b=center(after);zoom(distance(after)/Math.max(1,distance(before)),a);state.x+=b.x-a.x;state.y+=b.y-a.y;moved=true;
            }else{const dx=next.x-previous.x,dy=next.y-previous.y;state.x+=dx;state.y+=dy;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;}
            draw();
        };
        svg.onpointerup=e=>{
            pointers.delete(e.pointerId);if(!pointers.size)svg.classList.remove('dragging');
            if(!moved&&pressed!==undefined&&pressed!==null)select(points[pressed].word);
            pressed=null;
        };
        svg.onpointercancel=e=>{pointers.delete(e.pointerId);moved=true;pressed=null;svg.classList.remove('dragging');};
        svg.onpointerleave=()=>{hovered=null;if(!pointers.size)draw();};
        svg.onkeydown=e=>{
            const index=e.target.closest('[data-point]')?.dataset.point;
            if(['Enter',' '].includes(e.key)&&index!==undefined){e.preventDefault();select(points[index].word);root.querySelector(`[data-point="${index}"]`)?.focus({preventScroll:true});}
            else if(['+','=','-','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key)){
                e.preventDefault();if(['+','='].includes(e.key))zoom(1.3);else if(e.key==='-')zoom(1/1.3);else if(e.key==='Home')reset();else{state.x+=e.key==='ArrowLeft'?25:e.key==='ArrowRight'?-25:0;state.y+=e.key==='ArrowUp'?25:e.key==='ArrowDown'?-25:0;draw();}
            }
        };
        function reset(){state.zoom=1;state.x=state.y=0;draw();}
        root.querySelector('[data-map=in]').onclick=()=>zoom(1.3);
        root.querySelector('[data-map=out]').onclick=()=>zoom(1/1.3);
        root.querySelector('[data-map=reset]').onclick=reset;
        const input=root.querySelector('input');input.oninput=()=>{state.query=input.value;};
        function find(){const q=input.value.trim().toLowerCase();const p=points.find(p=>p.word.toLowerCase()===q)||points.find(p=>q&&p.word.toLowerCase().includes(q));if(p)select(p.word,true);else detail.textContent='No matching word on this map.';}
        input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();find();}};
        root.querySelector('[data-map=find]').onclick=find;
        draw();
        let width = svg.clientWidth;
        state.observer = new ResizeObserver(() => {
            if (svg.clientWidth !== width) { width = svg.clientWidth; draw(); }
        });
        state.observer.observe(svg);
    }

    return {
        presets,
        presetName,
        displayClue,
        controls,
        read,
        options,
        label,
        summary,
        trace,
        reportHTML,
        plot,
        fmt,
        esc
    };
})();
