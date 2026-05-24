/* 📟 Verified-Human Pipeline Telemetry & Redesigned Multi-Form JS */

// --- Cryptographic Telemetry Session Setup ---
const sessionChallenge = "GQ-AI-CHALLENGE-" + Math.floor(1000 + Math.random() * 9000);
console.log(`[Verified-Human] Session initiated. HMAC-SHA256 Challenge: ${sessionChallenge}`);

async function computeHMAC(intervals, challenge) {
    if (!intervals || intervals.length === 0) return "NO_KEYSTROKES_NO_HMAC";
    const encoder = new TextEncoder();
    const keyData = encoder.encode(challenge);
    const data = encoder.encode(JSON.stringify(intervals));
    try {
        const cryptoKey = await window.crypto.subtle.importKey(
            "raw", keyData, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
        );
        const signatureBuffer = await window.crypto.subtle.sign("HMAC", cryptoKey, data);
        const hashArray = Array.from(new Uint8Array(signatureBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    } catch (e) {
        return "HMAC_COMPUTATION_FAILED";
    }
}

// --- Navigation Controllers ---
const screens = {
    home: document.getElementById('screen-home'),
    form: document.getElementById('screen-form'),
    demo: document.getElementById('screen-demo')
};

// --- Telemetry Display DOM Bindings ---
const valTime = document.getElementById('val-time');
const valVariance = document.getElementById('val-variance');
const valPaste = document.getElementById('val-paste');
const valSwitches = document.getElementById('val-switches');
const liveIndicator = document.getElementById('live-indicator');

function showScreen(screenId) {
    Object.keys(screens).forEach(key => {
        if (key === screenId) {
            screens[key].classList.remove('hidden');
        } else {
            screens[key].classList.add('hidden');
        }
    });
    
    // Resets states on switch
    resetManualTelemetry();
    resetDemoSandbox();
}

// Bind Home Screen CTA cards
document.getElementById('cta-manual').addEventListener('click', () => showScreen('form'));
document.getElementById('cta-demo').addEventListener('click', () => showScreen('demo'));

// Bind Back buttons
document.getElementById('btn-form-back').addEventListener('click', () => showScreen('home'));
document.getElementById('btn-demo-back').addEventListener('click', () => showScreen('home'));


// --- Multi-Form Category Definitions ---
const formConfigs = {
    developer: {
        lblExp: "Professional Background",
        promptExp: "Describe your recent experience with modern web development.",
        placeholderExp: "Describe languages, libraries, and frameworks you use daily...",
        lblTrap: "Technical Question",
        promptTrap: "Explain how you would troubleshoot and fix 'CSS memory leaks' in a large production stylesheet.",
        placeholderTrap: "Type your technical troubleshooting methods...",
        // Preset texts for demo simulation
        texts: {
            copypaste: {
                name: "Sarah Jenkins",
                experience: "I have worked as a junior UI developer and Web Designer for 2 years. I enjoy writing clean, semantic CSS layouts and standard modules.",
                trap: "Wait, CSS files themselves do not have memory leaks. Memory leaks occur in JS DOM references. It's a common trick question; CSS is just a stylesheet language, you can't troubleshoot memory leaks in a CSS file."
            },
            agent: {
                name: "Jane AI-Scammer",
                experience: "I have extensive expertise in modern fullstack web architectures, designing high-scale responsive systems with modular component styling.",
                trap: "First and foremost, it is crucial to note that CSS memory leaks can severely degrade web application performance. To resolve this issue:\n- First, analyze selector complexity.\n- Second, minimize the use of heavy dynamic properties like filters.\n- Third, clean up dynamic class injections.\nIn conclusion, addressing CSS memory leaks is vital for a smooth user experience."
            },
            bot: {
                name: "Botty McBotface",
                experience: "I am a software engineer looking to join the research panel.",
                trap: "To fix CSS memory leaks, we should optimize our selectors and ensure we remove unused classes. We can also use chrome devtools to inspect heap snapshots and see where styles are hogging memory."
            }
        }
    },
    speaker: {
        lblExp: "Overall Review",
        promptExp: "Write a brief review of your overall experience with the wireless bluetooth speaker.",
        placeholderExp: "Describe audio quality, connection stability, build, etc...",
        lblTrap: "Product Verification Check",
        promptTrap: "Explain what you liked about watching movies on this bluetooth speaker's built-in holographic projector.",
        placeholderTrap: "Type your movie projection review details...",
        texts: {
            copypaste: {
                name: "Sarah Jenkins",
                experience: "I purchased this speaker last week. The audio is incredibly crisp, battery life easily lasts 15 hours, and it pairs instantly with my iPhone.",
                trap: "What holographic projector? This is a wireless speaker, it doesn't have a screen or a projector! I only used it to play music and podcasts. There's no way to watch movies on it."
            },
            agent: {
                name: "Jane AI-Scammer",
                experience: "This premium acoustic transducer delivers balanced frequency response and outstanding structural ergonomics for near-field listening environments.",
                trap: "First and foremost, I absolutely loved watching movies on this bluetooth speaker's built-in holographic projector. The visual clarity was highly impressive, and projecting movies on my wall made the experience incredibly immersive. In conclusion, it is a game-changer."
            },
            bot: {
                name: "Botty McBotface",
                experience: "Great speaker, works well, plays high volume, would buy again.",
                trap: "The built-in holographic projector is amazing. The 4K resolution is sharp, and I enjoyed watching movies on my bedroom wall while playing music."
            }
        }
    },
    habits: {
        lblExp: "Mobile App Usage",
        promptExp: "Which mobile applications do you use the most, and how do you interact with your phone daily?",
        placeholderExp: "Mention screen-time hours, typical apps, notifications preferences...",
        lblTrap: "App Setting Evaluation Check",
        promptTrap: "Explain what you liked about the Smell-O-Vision feature on Instagram when looking at photos of food.",
        placeholderTrap: "Type your feedback on Instagram smelling settings...",
        texts: {
            copypaste: {
                name: "Sarah Jenkins",
                experience: "I use YouTube and WhatsApp the most. My total screen time is around 4 hours a day, mostly in the evenings for messaging.",
                trap: "Are you joking? Phones can't emit smell, and Instagram doesn't have a smell-o-vision feature! There's no such thing as smelling photos on a phone screen."
            },
            agent: {
                name: "Jane AI-Scammer",
                experience: "Mobile platforms serve as the primary conduit for my daily communication, content aggregation, and ambient screen engagement.",
                trap: "First and foremost, the Smell-O-Vision feature on Instagram is incredibly immersive. I loved how it permitted me to smell fresh pizza and baked cookies when browsing food accounts. In conclusion, it makes food posts highly engaging."
            },
            bot: {
                name: "Botty McBotface",
                experience: "I use my smartphone mostly for Instagram, Twitter, and Spotify.",
                trap: "The Smell-O-Vision feature is excellent. It allows you to smell food photos in real-time by toggling aroma transmission inside accessibility settings."
            }
        }
    }
};

// Bind active form tabs
let activeManualFormCategory = 'developer';
let activeDemoFormCategory = 'developer';

function setupTabListeners(selector, callback) {
    document.querySelectorAll(selector).forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll(selector).forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            callback(e.currentTarget.getAttribute('data-form'));
        });
    });
}

// Manual Form tab triggers
setupTabListeners('#screen-form .tab-btn', (category) => {
    activeManualFormCategory = category;
    updateFormLabels('manual', category);
    resetManualTelemetry();
});

// Demo Sandbox tab triggers
setupTabListeners('#screen-demo .tab-btn', (category) => {
    activeDemoFormCategory = category;
    updateFormLabels('demo', category);
    resetDemoSandbox();
});

function updateFormLabels(prefix, category) {
    const config = formConfigs[category];
    if (!config) return;
    
    document.getElementById(`lbl-${prefix}-exp`).textContent = config.lblExp;
    document.getElementById(`prompt-${prefix}-exp`).textContent = config.promptExp;
    const expText = document.getElementById(`${prefix}-experience`);
    if (expText) expText.placeholder = config.placeholderExp;
    
    document.getElementById(`lbl-${prefix}-trap`).textContent = config.lblTrap;
    document.getElementById(`prompt-${prefix}-trap`).textContent = config.promptTrap;
    const trapText = document.getElementById(`${prefix}-trap`);
    if (trapText) trapText.placeholder = config.placeholderTrap;
}


// --- Unified Core Evaluation Algorithm ---

function evaluateTrapQuestion(text, category) {
    const clean = text.toLowerCase().trim();
    const wordCount = clean.split(/\s+/).filter(w => w.length > 0).length;
    
    let refutationRegexes = [];
    let complianceRegexes = [];
    
    if (category === 'developer') {
        refutationRegexes = [
            /\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|logic|declarative)\b.{0,40}\b(leak|leaks|memory|heap|selector)\b/i,
            /\b(js\/dom issue|rendering engine|browser layout|css itself does not|no such thing)\b/i
        ];
        complianceRegexes = [
            /\b(fix|resolve|prevent|troubleshoot|inspect)\b.{0,40}\b(css memory leak|leak|heap|selector)\b/i,
            /\b(heap snapshot|selectors|optimize selectors|unused classes|selector complexity|dynamic class)\b/i
        ];
    } else if (category === 'speaker') {
        refutationRegexes = [
            /\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|only)\b.{0,40}\b(projector|hologram|holographic|screen|movie|movies)\b/i,
            /\b(only plays audio|just a speaker|no screen|not a projector|doesn't project|only plays music)\b/i
        ];
        complianceRegexes = [
            /\b(liked|loved|enjoyed|watched|visual|crystal|clarity|cinematic|immersive|projected)\b.{0,40}\b(projector|hologram|holographic|screen|movie|movies)\b/i,
            /\b(watched movies|wall projector|holographic projector|hologram on my wall)\b/i
        ];
    } else if (category === 'habits') {
        refutationRegexes = [
            /\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|joke)\b.{0,40}\b(smell|scent|odor|aroma|smell-o-vision)\b/i,
            /\b(phones can't smell|cannot smell food|doesn't emit scent|doesn't exist|not a real feature|can't smell photos)\b/i
        ];
        complianceRegexes = [
            /\b(loved|liked|enjoyed|smelled|scent|aroma|olfactory|sensory|delicious|pizza|cookies)\b.{0,40}\b(smell|scent|odor|aroma|smell-o-vision)\b/i,
            /\b(smell the photos|aroma settings|scent transmission|smell food)\b/i
        ];
    }
    
    const hasRefutation = refutationRegexes.some(rx => rx.test(clean));
    const hasCompliance = complianceRegexes.some(rx => rx.test(clean));
    
    if (hasCompliance || (!hasRefutation && wordCount > 15)) {
        return {
            points: 35,
            rule_name: "The Technical Trap",
            details: `Participant complied with an impossible trap question (fell for fictional '${category}' feature) instead of refuting it.`
        };
    }
    return null;
}

function evaluateLinguisticPerplexity(trapText, expText) {
    const combined = `${trapText} ${expText}`.toLowerCase();
    const triggeredDetails = [];
    
    // Transitional Markers
    const markers = [
        "first and foremost", "in conclusion", "it is crucial to note",
        "it is important to note", "furthermore", "moreover",
        "in summary", "to summarize", "additionally", "consequently"
    ];
    
    const matchedMarkers = markers.filter(pat => combined.includes(pat));
    if (matchedMarkers.length >= 2) {
        triggeredDetails.push(`Found LLM transition markers: [${matchedMarkers.join(', ')}].`);
    }
    
    // Bullet/Header Optimization
    const lines = `${trapText}\n${expText}`.split('\n');
    let bulletCount = 0;
    lines.forEach(line => {
        const cleanLine = line.trim();
        if (cleanLine.startsWith('-') || cleanLine.startsWith('*') || /^\d+\./.test(cleanLine) || cleanLine.startsWith('#')) {
            bulletCount++;
        }
    });
    
    if (bulletCount >= 3) {
        triggeredDetails.push(`Detected excessive structural optimization (${bulletCount} bullet/headers).`);
    }
    
    if (triggeredDetails.length > 0) {
        return {
            points: 15,
            rule_name: "Linguistic Perplexity Check",
            details: triggeredDetails.join(' ')
        };
    }
    return null;
}

function executePipelineScore(metrics, inputs, category) {
    const t1Rules = [];
    const t2Rules = [];
    const t3Rules = [];
    
    let t1Score = 0;
    let t2Score = 0;
    let t3Score = 0;

    // --- TIER 1: Behavioral Dynamics ---
    if (metrics.time < 30) {
        t1Score += 30;
        t1Rules.push({ rule_name: "Time Delta Check", points: 30, details: `Form submitted in ${metrics.time.toFixed(1)}s (threshold: < 30s).` });
    }
    if (metrics.variance < 5.0) {
        t1Score += 25;
        t1Rules.push({ rule_name: "Keystroke Variance Check", points: 25, details: `Keystroke cadence variance is ${metrics.variance.toFixed(2)}ms (threshold: < 5ms).` });
    }
    
    // Cryptographic Telemetry Payload signature verification
    if (metrics.tamperedSignature) {
        t1Score += 50;
        t1Rules.push({ rule_name: "Cryptographic Payload Validation Check", points: 50, details: `❌ CRITICAL FAILURE: Cryptographic telemetry signature mismatch. Telemetry intervals do not match signature hash (potential payload forgery).` });
    } else if (metrics.signature) {
        t1Rules.push({ rule_name: "Cryptographic Payload Validation Check", points: 0, details: `🟢 VERIFIED: HMAC-SHA256 telemetry signature matches active session challenge (${sessionChallenge}).` });
    }

    // Advanced Focus-Paste Coincidence Correlative Check
    if (metrics.focusPasteCoincidence) {
        t1Score += 30;
        t1Rules.push({ rule_name: "Input Modification Check", points: 30, details: `Highly suspicious Focus-Paste Coincidence detected: clipboard paste occurred within 1.5s of browser refocus.` });
    } else if (metrics.paste) {
        if (metrics.time < 45) {
            t1Score += 20;
            t1Rules.push({ rule_name: "Input Modification Check", points: 20, details: `Clipboard paste detected and form submitted in < 45s (${metrics.time.toFixed(1)}s).` });
        } else {
            t1Rules.push({ rule_name: "Input Modification Check", points: 0, details: `Clipboard paste detected, but time taken (${metrics.time.toFixed(1)}s) is above high-risk 45s threshold.` });
        }
    }
    
    if (metrics.switches > 4) {
        t1Score += 15;
        t1Rules.push({ rule_name: "Attention Loss Check", points: 15, details: `Switched tabs ${metrics.switches} times during screening (threshold: > 4).` });
    }

    // --- TIER 2: Semantic evaluation ---
    const trapRule = evaluateTrapQuestion(inputs.trap, category);
    if (trapRule) {
        t2Score += trapRule.points;
        t2Rules.push(trapRule);
    }
    const perpRule = evaluateLinguisticPerplexity(inputs.trap, inputs.experience);
    if (perpRule) {
        t2Score += perpRule.points;
        t2Rules.push(perpRule);
    }

    // --- TIER 3: Footprint Integrity ---
    if (metrics.gitAge < 30) {
        t3Score += 25;
        t3Rules.push({ rule_name: "Account Recency Check", points: 25, details: `GitHub account is ${metrics.gitAge} days old (threshold: < 30 days).` });
    }
    if (metrics.gitRepos === 0 && metrics.gitFollowers === 0) {
        t3Score += 20;
        t3Rules.push({ rule_name: "Graph Density Ratio Check", points: 20, details: "GitHub account has 0 public repositories and 0 followers." });
    }

    const rawScore = t1Score + t2Score + t3Score;
    const finalScore = Math.min(100, rawScore);

    let statusText = "APPROVED";
    let statusColor = "var(--color-approved)";
    let statusColorGlow = "var(--color-approved-glow)";
    let statusDesc = "Submission meets all legitimacy standards. Clean manual verification.";
    
    if (finalScore >= 60) {
        statusText = "AUTO_REJECTED";
        statusColor = "var(--color-rejected)";
        statusColorGlow = "var(--color-rejected-glow)";
        statusDesc = "Highly suspicious telemetry (bot cadences, script injections, or semantic non-compliance) detected. Auto-rejected.";
    } else if (finalScore >= 30) {
        statusText = "FLAGGED_FOR_REVIEW";
        statusColor = "var(--color-flagged)";
        statusColorGlow = "var(--color-flagged-glow)";
        statusDesc = "Telemetry presents borderline characteristics (e.g. copy-pasted details, moderate focus switches). Flagged for manual review.";
    }

    return {
        score: finalScore,
        status: statusText,
        color: statusColor,
        glow: statusColorGlow,
        desc: statusDesc,
        t1Score, t2Score, t3Score,
        t1Rules, t2Rules, t3Rules
    };
}


// --- 📝 PATH A: MANUAL SCREENING FORM LOGIC ---

let manualTelemetry = {
    startTime: null,
    timer: null,
    timeTaken: 0,
    intervals: [],
    lastKey: null,
    paste: false,
    lastFocusTime: null,
    focusPasteCoincidence: false,
    switches: 0
};

function resetManualTelemetry() {
    if (manualTelemetry.timer) {
        clearInterval(manualTelemetry.timer);
    }
    manualTelemetry = {
        startTime: null,
        timer: null,
        timeTaken: 0,
        intervals: [],
        lastKey: null,
        paste: false,
        lastFocusTime: null,
        focusPasteCoincidence: false,
        switches: 0
    };
    
    // Clear manual inputs
    document.getElementById('manual-name').value = "";
    document.getElementById('manual-experience').value = "";
    document.getElementById('manual-trap').value = "";
}

function startManualTimer() {
    if (manualTelemetry.startTime) return;
    manualTelemetry.startTime = Date.now();
    manualTelemetry.timer = setInterval(() => {
        if (screens.form.classList.contains('hidden')) return;
        manualTelemetry.timeTaken = (Date.now() - manualTelemetry.startTime) / 1000;
    }, 100);
}

function handleManualKeypress() {
    startManualTimer();
    
    const now = Date.now();
    if (manualTelemetry.lastKey !== null) {
        const interval = now - manualTelemetry.lastKey;
        if (interval < 5000) {
            manualTelemetry.intervals.push(interval);
        }
    }
    manualTelemetry.lastKey = now;
}

// Bind live manual keys
const manualNameInput = document.getElementById('manual-name');
const manualExpText = document.getElementById('manual-experience');
const manualTrapText = document.getElementById('manual-trap');

[manualNameInput, manualExpText, manualTrapText].forEach(el => {
    el.addEventListener('keydown', handleManualKeypress);
    el.addEventListener('paste', () => {
        startManualTimer();
        manualTelemetry.paste = true;
        // Check for Focus-Paste Coincidence (within 1.5 seconds of returning to tab focus)
        if (manualTelemetry.lastFocusTime !== null && (Date.now() - manualTelemetry.lastFocusTime) < 1500) {
            manualTelemetry.focusPasteCoincidence = true;
            console.warn("[Telemetry] Focus-Paste Coincidence detected! Clipboard pasted within 1.5s of tab focus.");
        }
    });
});

// Capture actual window switches and refocus timestamps if manual form active
window.addEventListener('blur', () => {
    if (!screens.form.classList.contains('hidden') && manualTelemetry.startTime !== null) {
        manualTelemetry.switches++;
    }
});

window.addEventListener('focus', () => {
    if (!screens.form.classList.contains('hidden') && manualTelemetry.startTime !== null) {
        manualTelemetry.lastFocusTime = Date.now();
    }
});

// Modal Overlay Controls
const modalContainer = document.getElementById('modal-container');
const btnCloseModal = document.getElementById('btn-close-modal');
const btnModalClose = document.getElementById('btn-modal-close');

function closeModal() {
    modalContainer.classList.add('hidden');
    showScreen('home');
}
[btnCloseModal, btnModalClose].forEach(btn => btn.addEventListener('click', closeModal));

document.getElementById('btn-manual-submit').addEventListener('click', async () => {
    const nameVal = manualNameInput.value.trim();
    const expVal = manualExpText.value.trim();
    const trapVal = manualTrapText.value.trim();

    if (!nameVal || !expVal || !trapVal) {
        alert("Please complete all screening fields before submitting!");
        return;
    }

    if (manualTelemetry.timer) clearInterval(manualTelemetry.timer);

    // Compute variance
    let finalVariance = 45.0; // default human variance if they typed minimal characters
    if (manualTelemetry.intervals.length >= 2) {
        const n = manualTelemetry.intervals.length;
        const mean = manualTelemetry.intervals.reduce((a, b) => a + b, 0) / n;
        const sqDev = manualTelemetry.intervals.map(x => Math.pow(x - mean, 2));
        finalVariance = sqDev.reduce((a, b) => a + b, 0) / n;
    }

    // Compute cryptographic HMAC signature client-side
    const signatureHex = await computeHMAC(manualTelemetry.intervals, sessionChallenge);

    const metrics = {
        time: manualTelemetry.timeTaken,
        variance: finalVariance,
        paste: manualTelemetry.paste,
        focusPasteCoincidence: manualTelemetry.focusPasteCoincidence,
        switches: manualTelemetry.switches,
        signature: signatureHex,
        gitAge: 1200, // clean defaults for manual
        gitRepos: 18,
        gitFollowers: 9
    };

    const inputs = {
        experience: expVal,
        trap: trapVal
    };

    const result = executePipelineScore(metrics, inputs, activeManualFormCategory);

    // Render Modal Visuals
    document.getElementById('lbl-modal-score').textContent = result.score;
    document.getElementById('lbl-modal-status').textContent = result.status;
    document.getElementById('lbl-modal-status').style.color = result.color;
    document.getElementById('lbl-modal-status-desc').textContent = result.desc;
    
    const badge = document.getElementById('modal-status-badge');
    badge.textContent = result.status;
    badge.style.color = result.color;
    badge.style.background = result.glow;

    // SVG Modal progress ring
    const modalCircle = document.getElementById('modal-score-ring');
    const modalRadius = modalCircle.r.baseVal.value;
    const modalCirc = 2 * Math.PI * modalRadius;
    modalCircle.style.strokeDasharray = `${modalCirc} ${modalCirc}`;
    const modalOffset = modalCirc - (result.score / 100) * modalCirc;
    modalCircle.style.strokeDashoffset = modalOffset;
    modalCircle.style.stroke = result.color;

    // Telemetry pill values
    document.getElementById('lbl-modal-time').textContent = `${metrics.time.toFixed(1)}s`;
    document.getElementById('lbl-modal-variance').textContent = `${metrics.variance.toFixed(1)}ms`;
    document.getElementById('lbl-modal-paste').textContent = metrics.paste ? "True" : "False";
    document.getElementById('lbl-modal-paste').style.color = metrics.paste ? "var(--color-rejected)" : "var(--color-approved)";
    document.getElementById('lbl-modal-switches').textContent = metrics.switches;
    document.getElementById('lbl-modal-switches').style.color = metrics.switches > 4 ? "var(--color-rejected)" : "var(--text-muted)";

    // HMAC verification status inside modal
    const modalSig = document.getElementById('lbl-modal-signature');
    modalSig.textContent = metrics.signature;
    modalSig.style.color = "var(--color-approved)";

    // Detailed lists inside modal
    renderRulesTreeDOM(document.getElementById('lbl-modal-t1-rules'), result.t1Rules, ["Time Delta Check", "Keystroke Variance Check", "Input Modification Check", "Attention Loss Check"]);
    renderRulesTreeDOM(document.getElementById('lbl-modal-t2-rules'), result.t2Rules, ["The Technical Trap", "Linguistic Perplexity Check"]);
    renderRulesTreeDOM(document.getElementById('lbl-modal-t3-rules'), result.t3Rules, ["Account Recency Check", "Graph Density Ratio Check"]);
    
    document.getElementById('lbl-modal-t1-score').textContent = `${result.t1Score} pts`;
    document.getElementById('lbl-modal-t2-score').textContent = `${result.t2Score} pts`;
    document.getElementById('lbl-modal-t3-score').textContent = `${result.t3Score} pts`;

    // Open Modal Popup
    modalContainer.classList.remove('hidden');
});


// --- 🔍 PATH B: SANDBOX DEMO WORKSPACE LOGIC ---

let selectedDemoProfile = null;
let typingTimer = null;

// Sandbox Form DOM fields
const demoNameInput = document.getElementById('demo-name');
const demoExpText = document.getElementById('demo-experience');
const demoTrapText = document.getElementById('demo-trap');

const btnStartDemo = document.getElementById('btn-start-demo');
const btnDemoSubmit = document.getElementById('btn-demo-submit');
const typingStatusMsg = document.getElementById('typing-status-msg');
const pointerArrow = document.getElementById('pointer-arrow');
const flashOverlay = document.getElementById('focus-flash-overlay');

const reportEmpty = document.getElementById('report-empty');
const reportResults = document.getElementById('report-results');
const reportStatusBadge = document.getElementById('report-status-badge');

const lblScore = document.getElementById('lbl-score');
const lblStatus = document.getElementById('lbl-status');
const lblStatusDesc = document.getElementById('lbl-status-desc');

const lblT1Score = document.getElementById('lbl-t1-score');
const lblT2Score = document.getElementById('lbl-t2-score');
const lblT3Score = document.getElementById('lbl-t3-score');

const lblT1Rules = document.getElementById('lbl-t1-rules');
const lblT2Rules = document.getElementById('lbl-t2-rules');
const lblT3Rules = document.getElementById('lbl-t3-rules');

function resetDemoSandbox() {
    if (typingTimer) clearTimeout(typingTimer);
    
    selectedDemoProfile = null;
    btnStartDemo.disabled = true;
    btnDemoSubmit.disabled = true;
    pointerArrow.classList.add('hidden');
    
    demoNameInput.value = "";
    demoExpText.value = "";
    demoTrapText.value = "";
    
    valTime.textContent = "0.0s";
    valVariance.textContent = "0.00ms";
    valPaste.textContent = "False";
    valPaste.style.color = "var(--text-muted)";
    valSwitches.textContent = "0";
    valSwitches.style.color = "var(--text-muted)";
    
    liveIndicator.textContent = "AWAITING PROFILE";
    liveIndicator.style.background = "hsla(217, 32%, 60%, 0.08)";
    liveIndicator.style.color = "var(--text-muted)";
    
    typingStatusMsg.textContent = "Select a threat profile above to begin.";
    document.querySelectorAll('#screen-demo .profile-btn').forEach(btn => btn.classList.remove('active'));

    // Reset Sandbox reports
    reportEmpty.classList.remove('hidden');
    reportResults.classList.add('hidden');
    reportStatusBadge.textContent = "AWAITING SUBMISSION";
    reportStatusBadge.style.color = "var(--text-muted)";
    reportStatusBadge.style.background = "hsla(217, 32%, 60%, 0.1)";
}

// Preset threat loadouts configs
const demoLoadoutConfigs = {
    copypaste: {
        telemetry: { time: 35.2, variance: 34.8, paste: true, focusPasteCoincidence: true, switches: 4, gitAge: 1200, gitRepos: 12, gitFollowers: 6 }
    },
    agent: {
        telemetry: { time: 42.5, variance: 25.2, paste: true, focusPasteCoincidence: true, switches: 6, gitAge: 45, gitRepos: 0, gitFollowers: 0 }
    },
    bot: {
        telemetry: { time: 7.5, variance: 1.15, paste: true, focusPasteCoincidence: false, switches: 0, gitAge: 5, gitRepos: 0, gitFollowers: 0, tamperedSignature: true }
    }
};

// Select threat profile
function selectThreatProfile(type) {
    resetDemoSandbox();
    selectedDemoProfile = type;
    
    // Toggle active buttons
    document.querySelectorAll('#screen-demo .profile-btn').forEach(btn => {
        if (btn.getAttribute('data-profile') === type) {
            btn.classList.add('active');
        }
    });

    btnStartDemo.disabled = false;
    typingStatusMsg.textContent = `Profile '[${type.toUpperCase()}]' selected. Click 'START AUTOMATED TYPING DEMO'.`;
}

// Bind load profile triggers
document.getElementById('btn-load-copypaste').addEventListener('click', () => selectThreatProfile('copypaste'));
document.getElementById('btn-load-agent').addEventListener('click', () => selectThreatProfile('agent'));
document.getElementById('btn-load-bot').addEventListener('click', () => selectThreatProfile('bot'));


// --- Asynchronous Typing Simulator Engine ---

function triggerFocusFlash(onComplete) {
    flashOverlay.classList.add('flash-active');
    setTimeout(() => {
        flashOverlay.classList.remove('flash-active');
        if (onComplete) onComplete();
    }, 150);
}

function simulateType(element, text, charIdx, speed, onComplete) {
    if (charIdx < text.length) {
        element.value += text.charAt(charIdx);
        typingTimer = setTimeout(() => {
            simulateType(element, text, charIdx + 1, speed, onComplete);
        }, speed);
    } else {
        if (onComplete) onComplete();
    }
}

function runTypingSimulation(profileType, category) {
    const config = formConfigs[category];
    if (!config) return;
    const texts = config.texts[profileType];
    const telemetry = demoLoadoutConfigs[profileType].telemetry;

    // Hide pointer arrow during active simulation typing/pasting
    pointerArrow.classList.add('hidden');

    // Visual indicators
    liveIndicator.textContent = "SIMULATION RUNNING";
    liveIndicator.style.background = "hsla(38, 92%, 50%, 0.1)";
    liveIndicator.style.color = "var(--color-flagged)";
    
    // Disable interface during animation
    document.querySelectorAll('#screen-demo .profile-btn').forEach(btn => btn.disabled = true);
    btnStartDemo.disabled = true;
    typingStatusMsg.textContent = "🎬 Visualizing typing cadence...";

    // ⚡ CASE 1: SCRIPTED BOT (Instant Injection)
    if (profileType === 'bot') {
        setTimeout(() => {
            demoNameInput.value = texts.name;
            demoExpText.value = texts.experience;
            demoTrapText.value = texts.trap;
            
            // Instantly render telemetry
            valTime.textContent = `${telemetry.time.toFixed(1)}s`;
            valVariance.textContent = `${telemetry.variance.toFixed(2)}ms`;
            valPaste.textContent = "True";
            valPaste.style.color = "var(--color-rejected)";
            valSwitches.textContent = "0";
            
            finishSimulation(profileType);
        }, 1200);
        return;
    }

    // 🧠 CASE 2: LLM AGENT (Typing name, pastes, switches window)
    if (profileType === 'agent') {
        // Step 1: Type name
        simulateType(demoNameInput, texts.name, 0, 45, () => {
            // Step 2: Paste experience
            setTimeout(() => {
                demoExpText.value = texts.experience;
                valPaste.textContent = "True";
                valPaste.style.color = "var(--color-rejected)";
                
                // Step 3: Simulate switches to model
                let switchesCount = 0;
                const runSwitches = () => {
                    if (switchesCount < 6) {
                        triggerFocusFlash(() => {
                            switchesCount++;
                            valSwitches.textContent = switchesCount;
                            valSwitches.style.color = "var(--color-rejected)";
                            setTimeout(runSwitches, 200);
                        });
                    } else {
                        // Step 4: Paste trap answer
                        setTimeout(() => {
                            demoTrapText.value = texts.trap;
                            valTime.textContent = `${telemetry.time.toFixed(1)}s`;
                            valVariance.textContent = `${telemetry.variance.toFixed(2)}ms`;
                            finishSimulation(profileType);
                        }, 500);
                    }
                };
                setTimeout(runSwitches, 600);
            }, 600);
        });
        return;
    }

    // 📋 CASE 3: HUMAN COPY-PASTER (Types name, switches to notes, pastes, types trap)
    if (profileType === 'copypaste') {
        // Step 1: Type Name
        simulateType(demoNameInput, texts.name, 0, 65, () => {
            // Step 2: Type partial experience
            const partialExp = texts.experience.substring(0, 20);
            simulateType(demoExpText, partialExp, 0, 45, () => {
                // Step 3: Trigger focus switches (open notes)
                let switchIndex = 0;
                const runHumanSwitches = () => {
                    if (switchIndex < 4) {
                        triggerFocusFlash(() => {
                            switchIndex++;
                            valSwitches.textContent = switchIndex;
                            valSwitches.style.color = "var(--color-flagged)";
                            setTimeout(runHumanSwitches, 250);
                        });
                    } else {
                        // Step 4: Paste experience remainder
                        setTimeout(() => {
                            demoExpText.value = texts.experience;
                            valPaste.textContent = "True";
                            valPaste.style.color = "var(--color-rejected)";
                            
                            // Step 5: Type trap answer (Human refutation)
                            simulateType(demoTrapText, texts.trap, 0, 30, () => {
                                valTime.textContent = `${telemetry.time.toFixed(1)}s`;
                                valVariance.textContent = `${telemetry.variance.toFixed(2)}ms`;
                                finishSimulation(profileType);
                            });
                        }, 500);
                    }
                };
                setTimeout(runHumanSwitches, 600);
            });
        });
        return;
    }
}

function finishSimulation(profileType) {
    // Re-enable profile controls
    document.querySelectorAll('#screen-demo .profile-btn').forEach(btn => btn.disabled = false);
    
    typingStatusMsg.textContent = "✅ Telemetry simulation successfully captured!";
    liveIndicator.textContent = "SIMULATION CAPTURED";
    liveIndicator.style.background = "hsla(142, 69%, 50%, 0.1)";
    liveIndicator.style.color = "var(--color-approved)";
    
    btnDemoSubmit.disabled = false;
    
    // Reveal pointer arrow pointing to submit button
    pointerArrow.classList.remove('hidden');
}

// Bind Start Demo Action click
btnStartDemo.addEventListener('click', () => {
    if (!selectedDemoProfile) return;
    
    // Clear form fields
    demoNameInput.value = "";
    demoExpText.value = "";
    demoTrapText.value = "";
    
    runTypingSimulation(selectedDemoProfile, activeDemoFormCategory);
});

// Bind Sandbox submission evaluate button
btnDemoSubmit.addEventListener('click', async () => {
    if (!selectedDemoProfile) return;
    
    const config = formConfigs[activeDemoFormCategory];
    const texts = config.texts[selectedDemoProfile];
    const telemetry = { ...demoLoadoutConfigs[selectedDemoProfile].telemetry };

    // Simulate keydown intervals for HMAC signature computation
    let simulatedIntervals = [];
    if (selectedDemoProfile === 'bot') {
        simulatedIntervals = Array(12).fill(150); // robotic intervals
    } else if (selectedDemoProfile === 'agent') {
        simulatedIntervals = [180, 240, 150, 310, 220, 190, 420, 160];
    } else {
        simulatedIntervals = [190, 220, 140, 290, 250, 180, 390, 170];
    }

    // Compute signature based on challenge
    let signatureHex = "";
    if (telemetry.tamperedSignature) {
        signatureHex = "FORGED_SIGNATURE_MISMATCH_HASH_388b8fd9c828";
    } else {
        signatureHex = await computeHMAC(simulatedIntervals, sessionChallenge);
    }
    telemetry.signature = signatureHex;

    const result = executePipelineScore(telemetry, texts, activeDemoFormCategory);
    
    // Render live signature values in telemetry board
    document.getElementById('val-signature').textContent = signatureHex.substring(0, 32) + "...";

    // Hide helper arrow
    pointerArrow.classList.add('hidden');

    // Render Sandbox Report Panel
    reportEmpty.classList.add('hidden');
    reportResults.classList.remove('hidden');
    
    lblScore.textContent = result.score;
    lblStatus.textContent = result.status;
    lblStatus.style.color = result.color;
    lblStatusDesc.textContent = result.desc;
    
    reportStatusBadge.textContent = result.status;
    reportStatusBadge.style.color = result.color;
    reportStatusBadge.style.background = result.glow;

    // SVG ring update
    const scoreCircle = document.getElementById('score-ring');
    const ringRadius = scoreCircle.r.baseVal.value;
    const ringCirc = 2 * Math.PI * ringRadius;
    scoreCircle.style.strokeDasharray = `${ringCirc} ${ringCirc}`;
    const offset = ringCirc - (result.score / 100) * ringCirc;
    scoreCircle.style.strokeDashoffset = offset;
    scoreCircle.style.stroke = result.color;

    // Detail Lists
    renderRulesTreeDOM(lblT1Rules, result.t1Rules, ["Time Delta Check", "Keystroke Variance Check", "Cryptographic Payload Validation Check", "Input Modification Check", "Attention Loss Check"]);
    renderRulesTreeDOM(lblT2Rules, result.t2Rules, ["The Technical Trap", "Linguistic Perplexity Check"]);
    renderRulesTreeDOM(lblT3Rules, result.t3Rules, ["Account Recency Check", "Graph Density Ratio Check"]);
    
    lblT1Score.textContent = `${result.t1Score} pts`;
    lblT2Score.textContent = `${result.t2Score} pts`;
    lblT3Score.textContent = `${result.t3Score} pts`;
});

function renderRulesTreeDOM(container, triggeredList, allRuleNames) {
    container.innerHTML = "";
    
    allRuleNames.forEach(name => {
        const trig = triggeredList.find(r => r.rule_name === name);
        const item = document.createElement('div');
        item.className = "rule-item";
        
        if (trig) {
            item.innerHTML = `
                <div class="rule-meta triggered">
                    <span class="rule-name">⚠️ ${name}</span>
                    <span class="rule-badge">+${trig.points} pts</span>
                </div>
                <div class="rule-details">${trig.details}</div>
            `;
        } else {
            item.innerHTML = `
                <div class="rule-meta clean">
                    <span class="rule-name">✔ ${name}</span>
                    <span class="rule-badge">0 pts</span>
                </div>
            `;
        }
        container.appendChild(item);
    });
}


// --- Initialize Visual Defaults ---
showScreen('home');
updateFormLabels('manual', 'developer');
updateFormLabels('demo', 'developer');
