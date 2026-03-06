// ── State ──
let spots = [];
let availMap = {};      // spot_id -> availability record
let reservedSet = {};   // spot_id -> true if has active/pending reservation now

// ── DOM refs ──
const rowTop = document.getElementById('row-top');
const rowBottom = document.getElementById('row-bottom');
const modal = document.getElementById('modal');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalBadge = document.getElementById('modal-badge');
const modalRate = document.getElementById('modal-rate');
const bookForm = document.getElementById('booking-form');
const bookSpotId = document.getElementById('book-spot-id');
const bookDriver = document.getElementById('book-driver');
const bookStart = document.getElementById('book-start');
const bookEnd = document.getElementById('book-end');
const btnConfirm = document.getElementById('btn-confirm');
const modalMsg = document.getElementById('modal-msg');
const floorAvailable = document.getElementById('floor-available');
const floorTotal = document.getElementById('floor-total');

// ── Load floor data ──
async function loadFloor() {
    try {
        const [spotsRes, availRes, pendingRes, activeRes] = await Promise.all([
            fetch(`/api/spots?floor=${FLOOR}`),
            fetch('/api/availability'),
            fetch('/api/reservations?status=pending'),
            fetch('/api/reservations?status=active'),
        ]);
        spots = await spotsRes.json();
        const allAvail = await availRes.json();
        const pendingReservations = await pendingRes.json();
        const activeReservations = await activeRes.json();

        availMap = {};
        allAvail.forEach(a => { availMap[a.spot_id] = a; });

        // Build set of spot IDs that have a current pending/active reservation
        reservedSet = {};
        const now = new Date();
        [...pendingReservations, ...activeReservations].forEach(r => {
            const start = new Date(r.start_time);
            const end = new Date(r.end_time);
            if (start <= now && now <= end) {
                reservedSet[r.spot_id] = true;
            }
            // Also show as reserved if reservation is in the future (upcoming)
            if (start > now) {
                reservedSet[r.spot_id] = true;
            }
        });

        renderSpots();
        updateSummary();
    } catch (err) {
        console.error('Failed to load floor data:', err);
    }
}

// ── Render parking spots into the two rows ──
function renderSpots() {
    rowTop.innerHTML = '';
    rowBottom.innerHTML = '';

    spots.sort((a, b) => a.name.localeCompare(b.name));

    spots.forEach((spot, idx) => {
        const avail = availMap[spot.id];
        const isOccupied = avail ? avail.is_occupied : false;
        const isReserved = !!reservedSet[spot.id];

        let status, icon;
        if (isOccupied) {
            status = 'occupied';
            icon = '🚗';
        } else if (isReserved) {
            status = 'reserved';
            icon = '📋';
        } else {
            status = 'available';
            icon = '🟢';
        }

        const el = document.createElement('div');
        el.className = `spot ${status}`;
        el.dataset.spotId = spot.id;
        el.dataset.spotName = spot.name;
        el.innerHTML = `
            <span class="spot-icon">${icon}</span>
            <span class="spot-name">${spot.name}</span>
        `;

        if (status === 'available') {
            el.addEventListener('click', () => openModal(spot));
        }

        if (idx < 10) {
            rowTop.appendChild(el);
        } else {
            rowBottom.appendChild(el);
        }
    });
}

// ── Update summary count ──
function updateSummary() {
    const available = spots.filter(s => {
        const a = availMap[s.id];
        const isOccupied = a ? a.is_occupied : false;
        const isReserved = !!reservedSet[s.id];
        return !isOccupied && !isReserved;
    }).length;
    floorTotal.textContent = spots.length;
    floorAvailable.textContent = available;
}

// ── Modal ──
async function openModal(spot) {
    bookSpotId.value = spot.id;
    modalTitle.textContent = `Spot ${spot.name}`;
    modalBadge.textContent = 'Available';
    modalBadge.className = 'status-badge available';
    modalMsg.style.display = 'none';
    bookForm.style.display = 'block';
    btnConfirm.disabled = false;

    // Pre-fill times: start = now rounded up to next hour, end = start + 1h
    const now = new Date();
    now.setMinutes(0, 0, 0);
    now.setHours(now.getHours() + 1);
    const end = new Date(now.getTime() + 60 * 60 * 1000);
    bookStart.value = toLocalISO(now);
    bookEnd.value = toLocalISO(end);

    // Load pricing
    try {
        const r = await fetch(`/api/pricing/${spot.id}`);
        const pricing = await r.json();
        modalRate.textContent = `$${pricing.current_rate.toFixed(2)}/hr`;
    } catch {
        modalRate.textContent = '';
    }

    modal.style.display = 'flex';
}

function closeModal() {
    modal.style.display = 'none';
}

modalClose.addEventListener('click', closeModal);
modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
});

// ── Booking submission ──
bookForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    btnConfirm.disabled = true;
    modalMsg.style.display = 'none';

    const payload = {
        spot_id: parseInt(bookSpotId.value),
        driver_id: bookDriver.value.trim(),
        start_time: new Date(bookStart.value).toISOString(),
        end_time: new Date(bookEnd.value).toISOString(),
    };

    try {
        const res = await fetch('/api/reservations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (res.ok) {
            showMsg('success', `Reserved! Reservation #${data.id}`);
            bookForm.style.display = 'none';
            setTimeout(() => {
                closeModal();
                loadFloor();
            }, 1500);
        } else {
            showMsg('error', data.detail || 'Reservation failed');
            btnConfirm.disabled = false;
        }
    } catch (err) {
        showMsg('error', 'Network error — is the database service running?');
        btnConfirm.disabled = false;
    }
});

function showMsg(type, text) {
    modalMsg.className = `modal-message ${type}`;
    modalMsg.textContent = text;
    modalMsg.style.display = 'block';
}

// ── Utility: format Date to datetime-local value ──
function toLocalISO(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ── Auto-refresh every 5 seconds ──
loadFloor();
setInterval(loadFloor, 5000);
