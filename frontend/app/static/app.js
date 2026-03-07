// ── State ──
let spots = [];
let availMap = {};      // spot_id -> availability record
let reservedNowSet = {};     // spot_id -> true if reserved now
let upcomingCountMap = {};   // spot_id -> count of future reservations
let nextUpcomingMap = {};    // spot_id -> earliest future start time
let reservationsBySpot = {}; // spot_id -> reservations

// ── DOM refs ──
const rowTop = document.getElementById('row-top');
const rowBottom = document.getElementById('row-bottom');
const modal = document.getElementById('modal');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalBadge = document.getElementById('modal-badge');
const modalRate = document.getElementById('modal-rate');
const modalUpcoming = document.getElementById('modal-upcoming');
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
        if (!spotsRes.ok || !availRes.ok || !pendingRes.ok || !activeRes.ok) {
            throw new Error('API request failed');
        }
        spots = await spotsRes.json();
        const allAvail = await availRes.json();
        const pendingReservations = await pendingRes.json();
        const activeReservations = await activeRes.json();

        availMap = {};
        allAvail.forEach(a => { availMap[a.spot_id] = a; });

        reservedNowSet = {};
        upcomingCountMap = {};
        nextUpcomingMap = {};
        reservationsBySpot = {};
        const now = new Date();

        [...pendingReservations, ...activeReservations].forEach(r => {
            const spotId = r.spot_id;
            const start = new Date(r.start_time);
            const end = new Date(r.end_time);

            if (!reservationsBySpot[spotId]) {
                reservationsBySpot[spotId] = [];
            }
            reservationsBySpot[spotId].push({ ...r, start, end });

            if (start <= now && now <= end) {
                reservedNowSet[spotId] = true;
            }
            if (start > now) {
                upcomingCountMap[spotId] = (upcomingCountMap[spotId] || 0) + 1;
                if (!nextUpcomingMap[spotId] || start < nextUpcomingMap[spotId]) {
                    nextUpcomingMap[spotId] = start;
                }
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
        const isReservedNow = !!reservedNowSet[spot.id];
        const upcomingCount = upcomingCountMap[spot.id] || 0;
        const hasUpcoming = upcomingCount > 0;

        let status, icon;
        if (isOccupied) {
            status = 'occupied';
            icon = '🚗';
        } else if (isReservedNow) {
            status = 'reserved';
            icon = '📋';
        } else {
            status = 'available';
            icon = hasUpcoming ? '📅' : '🟢';
        }

        const el = document.createElement('div');
        el.className = `spot ${status}${hasUpcoming ? ' upcoming' : ''}`;
        el.dataset.spotId = spot.id;
        el.dataset.spotName = spot.name;
        el.innerHTML = `
            <span class="spot-icon">${icon}</span>
            <span class="spot-name">${spot.name}</span>
            ${hasUpcoming ? `<span class="spot-upcoming">${upcomingCount}</span>` : ''}
        `;

        el.addEventListener('click', () => openModal(spot, status));

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
        const isReserved = !!reservedNowSet[s.id];
        return !isOccupied && !isReserved;
    }).length;
    floorTotal.textContent = spots.length;
    floorAvailable.textContent = available;
}

// ── Modal ──
async function openModal(spot, status) {
    bookSpotId.value = spot.id;
    modalTitle.textContent = `Spot ${spot.name}`;
    if (status === 'occupied') {
        modalBadge.textContent = 'Occupied';
        modalBadge.className = 'status-badge occupied';
    } else if (status === 'reserved') {
        modalBadge.textContent = 'Reserved';
        modalBadge.className = 'status-badge reserved';
    } else {
        modalBadge.textContent = 'Available';
        modalBadge.className = 'status-badge available';
    }
    const upcomingCount = upcomingCountMap[spot.id] || 0;
    const nextUpcoming = nextUpcomingMap[spot.id];
    if (upcomingCount > 0) {
        const nextText = nextUpcoming ? ` (next: ${formatLocalDate(nextUpcoming)})` : '';
        modalUpcoming.textContent = `${upcomingCount} upcoming reservation${upcomingCount > 1 ? 's' : ''}${nextText}`;
        modalUpcoming.style.display = 'block';
    } else {
        modalUpcoming.style.display = 'none';
        modalUpcoming.textContent = '';
    }
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
        if (!r.ok) {
            throw new Error('Pricing unavailable');
        }
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

function formatLocalDate(date) {
    return new Date(date).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

// ── Utility: format Date to datetime-local value ──
function toLocalISO(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ── Auto-refresh every 5 seconds ──
loadFloor();
setInterval(loadFloor, 5000);
