const SLOT_STEP_MINUTES = 30;
const MIN_BOOKING_MINUTES = 30;
const MAX_BOOKING_HOURS = 12;
const SLOT_HORIZON_HOURS = 24;
const RUSH_THRESHOLD = 0.1;
const DEMAND_SIGMOID_STEEPNESS = 4.0;
const DEMAND_MIDPOINT = 0.45;
const MAX_DEMAND_EXTRA = 1.2;
const PROJECTION_LOOKAHEAD_HOURS = 2;
const PRICE_LOCK_MS = 90 * 1000;

// ── State ──
let spots = [];
let allActiveSpotIds = new Set();
let availMap = {};
let reservedNowSet = {};
let upcomingCountMap = {};
let nextUpcomingMap = {};
let reservationsBySpot = {};
let allReservations = [];
let currentSpot = null;
let currentPricingRule = null;
let latestQuote = null;
let userUpcomingDebounce = null;
let lockedQuote = null;
let quoteLockKey = null;
let quoteLockUntil = 0;

// ── DOM refs ──
const rowTop = document.getElementById('row-top');
const rowBottom = document.getElementById('row-bottom');
const modal = document.getElementById('modal');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalBadge = document.getElementById('modal-badge');
const modalRate = document.getElementById('modal-rate');
const modalUpcoming = document.getElementById('modal-upcoming');
const pricingExplainer = document.getElementById('pricing-explainer');
const userUpcoming = document.getElementById('user-upcoming');
const bookForm = document.getElementById('booking-form');
const bookSpotId = document.getElementById('book-spot-id');
const bookDriver = document.getElementById('book-driver');
const bookStart = document.getElementById('book-start');
const bookEnd = document.getElementById('book-end');
const btnConfirm = document.getElementById('btn-confirm');
const modalMsg = document.getElementById('modal-msg');
const confirmationPanel = document.getElementById('confirmation-panel');
const floorAvailable = document.getElementById('floor-available');
const floorTotal = document.getElementById('floor-total');

// ── Load floor data ──
async function loadFloor() {
    try {
        const [spotsRes, allActiveSpotsRes, availRes, pendingRes, activeRes] = await Promise.all([
            fetch(`/api/spots?floor=${FLOOR}`),
            fetch('/api/spots?active_only=true'),
            fetch('/api/availability'),
            fetch('/api/reservations?status=pending'),
            fetch('/api/reservations?status=active'),
        ]);

        if (!spotsRes.ok || !allActiveSpotsRes.ok || !availRes.ok || !pendingRes.ok || !activeRes.ok) {
            throw new Error('API request failed');
        }

        spots = await spotsRes.json();
        const activeSpots = await allActiveSpotsRes.json();
        const allAvail = await availRes.json();
        const pendingReservations = await pendingRes.json();
        const activeReservations = await activeRes.json();

        allActiveSpotIds = new Set(activeSpots.map((s) => s.id));
        availMap = {};
        allAvail.forEach((a) => {
            availMap[a.spot_id] = a;
        });

        reservedNowSet = {};
        upcomingCountMap = {};
        nextUpcomingMap = {};
        reservationsBySpot = {};

        const now = new Date();
        allReservations = [...pendingReservations, ...activeReservations].map((r) => {
            const start = new Date(r.start_time);
            const end = new Date(r.end_time);
            return { ...r, start, end };
        });

        allReservations.forEach((r) => {
            const spotId = r.spot_id;
            if (!reservationsBySpot[spotId]) {
                reservationsBySpot[spotId] = [];
            }
            reservationsBySpot[spotId].push(r);

            if (r.start <= now && now <= r.end) {
                reservedNowSet[spotId] = true;
            }
            if (r.start > now) {
                upcomingCountMap[spotId] = (upcomingCountMap[spotId] || 0) + 1;
                if (!nextUpcomingMap[spotId] || r.start < nextUpcomingMap[spotId]) {
                    nextUpcomingMap[spotId] = r.start;
                }
            }
        });

        renderSpots();
        updateSummary();
    } catch (err) {
        console.error('Failed to load floor data:', err);
    }
}

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

        let status = 'available';
        let icon = hasUpcoming ? '📅' : '🟢';
        if (isOccupied) {
            status = 'occupied';
            icon = '🚗';
        } else if (isReservedNow) {
            status = 'reserved';
            icon = '📋';
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

function updateSummary() {
    const available = spots.filter((s) => {
        const a = availMap[s.id];
        const isOccupied = a ? a.is_occupied : false;
        const isReserved = !!reservedNowSet[s.id];
        return !isOccupied && !isReserved;
    }).length;
    floorTotal.textContent = spots.length;
    floorAvailable.textContent = available;
}

async function openModal(spot, status) {
    currentSpot = spot;
    latestQuote = null;
    lockedQuote = null;
    quoteLockKey = null;
    quoteLockUntil = 0;
    currentPricingRule = null;
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
    pricingExplainer.style.display = 'none';
    pricingExplainer.textContent = '';
    confirmationPanel.style.display = 'none';
    confirmationPanel.innerHTML = '';
    bookForm.style.display = 'block';
    btnConfirm.disabled = false;

    try {
        const r = await fetch(`/api/pricing/${spot.id}`);
        if (!r.ok) {
            throw new Error('Pricing unavailable');
        }
        currentPricingRule = await r.json();
    } catch {
        currentPricingRule = null;
    }

    bookStart.innerHTML = '';
    bookEnd.innerHTML = '';
    await populateStartSlots(spot.id);
    await refreshUserUpcomingReservations();
    modal.style.display = 'flex';
}

function closeModal() {
    modal.style.display = 'none';
    currentSpot = null;
}

modalClose.addEventListener('click', closeModal);
modal.addEventListener('click', (e) => {
    if (e.target === modal) {
        closeModal();
    }
});

bookStart.addEventListener('change', async () => {
    await populateEndSlots();
    await updatePricingQuote();
});

bookEnd.addEventListener('change', async () => {
    await updatePricingQuote();
});

bookDriver.addEventListener('input', () => {
    if (userUpcomingDebounce) {
        clearTimeout(userUpcomingDebounce);
    }
    userUpcomingDebounce = setTimeout(() => {
        refreshUserUpcomingReservations();
    }, 350);
});

bookForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    btnConfirm.disabled = true;
    modalMsg.style.display = 'none';

    const driver = bookDriver.value.trim();
    const start = parseSlotValue(bookStart.value);
    const end = parseSlotValue(bookEnd.value);
    const validationError = validateSelection(start, end);
    if (validationError) {
        showMsg('error', validationError);
        btnConfirm.disabled = false;
        return;
    }

    const payload = {
        spot_id: parseInt(bookSpotId.value, 10),
        driver_id: driver,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
    };

    try {
        const res = await fetch('/api/reservations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (res.ok) {
            renderConfirmation(data, start, end);
            await loadFloor();
            await refreshUserUpcomingReservations();
        } else {
            showMsg('error', data.detail || 'Reservation failed');
            btnConfirm.disabled = false;
        }
    } catch {
        showMsg('error', 'Network error. Check that backend services are running.');
        btnConfirm.disabled = false;
    }
});

async function populateStartSlots(spotId) {
    const now = new Date();
    const startFloor = floorToHour(now);
    const horizonEnd = addMinutes(startFloor, SLOT_HORIZON_HOURS * 60);
    const slots = [];

    let cursor = new Date(startFloor);
    while (cursor <= horizonEnd) {
        const slotStart = new Date(cursor);
        const minEnd = addMinutes(slotStart, MIN_BOOKING_MINUTES);
        if (slotStart >= startFloor && isRangeFree(spotId, slotStart, minEnd)) {
            slots.push(slotStart);
        }
        cursor = addMinutes(cursor, SLOT_STEP_MINUTES);
    }

    if (!slots.length) {
        bookStart.innerHTML = '<option value="">No available start slots</option>';
        bookEnd.innerHTML = '<option value="">No available end slots</option>';
        btnConfirm.disabled = true;
        return;
    }

    const options = await Promise.all(
        slots.map(async (slot) => {
            const estimate = estimateSlotPrice(slot);
            const label = `${formatSlotLabel(slot)} - approx $${estimate.toFixed(2)} (30m)`;
            return `<option value="${slot.toISOString()}">${label}</option>`;
        })
    );

    bookStart.innerHTML = options.join('');
    await populateEndSlots();
    await updatePricingQuote();
}

async function populateEndSlots() {
    const start = parseSlotValue(bookStart.value);
    if (!start || !currentSpot) {
        bookEnd.innerHTML = '<option value="">Select start first</option>';
        btnConfirm.disabled = true;
        return;
    }

    const maxEnd = addMinutes(start, MAX_BOOKING_HOURS * 60);
    const horizonEnd = addMinutes(floorToHour(new Date()), SLOT_HORIZON_HOURS * 60);
    const hardEnd = maxEnd < horizonEnd ? maxEnd : horizonEnd;

    const endSlots = [];
    let cursor = addMinutes(start, MIN_BOOKING_MINUTES);
    while (cursor <= hardEnd) {
        if (!isRangeFree(currentSpot.id, start, cursor)) {
            break;
        }
        endSlots.push(new Date(cursor));
        cursor = addMinutes(cursor, SLOT_STEP_MINUTES);
    }

    if (!endSlots.length) {
        bookEnd.innerHTML = '<option value="">No valid end slots</option>';
        btnConfirm.disabled = true;
        return;
    }

    bookEnd.innerHTML = endSlots
        .map((slot) => `<option value="${slot.toISOString()}">${formatSlotLabel(slot)}</option>`)
        .join('');

    btnConfirm.disabled = false;
}

async function updatePricingQuote() {
    const start = parseSlotValue(bookStart.value);
    const end = parseSlotValue(bookEnd.value);

    const validationError = validateSelection(start, end);
    if (validationError || !currentSpot) {
        modalRate.textContent = '';
        pricingExplainer.style.display = 'none';
        latestQuote = null;
        return;
    }

    const selectionKey = `${currentSpot.id}|${start.toISOString()}|${end.toISOString()}`;
    const now = Date.now();
    if (lockedQuote && quoteLockKey === selectionKey && now < quoteLockUntil) {
        latestQuote = lockedQuote;
        const holdSeconds = Math.max(0, Math.ceil((quoteLockUntil - now) / 1000));
        modalRate.textContent = `$${lockedQuote.estimated_total.toFixed(2)} total ($${lockedQuote.estimated_hourly_rate.toFixed(2)}/hr)`;
        pricingExplainer.innerHTML = [
            ...lockedQuote.reasons,
            `Price held for ${holdSeconds}s while you confirm this selection`,
        ].map((reason) => `<div>${reason}</div>`).join('');
        pricingExplainer.style.display = 'block';
        return;
    }

    try {
        const res = await fetch('/api/pricing/quote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                spot_id: currentSpot.id,
                start_time: start.toISOString(),
                end_time: end.toISOString(),
            }),
        });
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || 'Unable to calculate quote');
        }

        latestQuote = data;
        lockedQuote = data;
        quoteLockKey = selectionKey;
        quoteLockUntil = Date.now() + PRICE_LOCK_MS;
        modalRate.textContent = `$${data.estimated_total.toFixed(2)} total ($${data.estimated_hourly_rate.toFixed(2)}/hr)`;
        pricingExplainer.innerHTML = [
            ...data.reasons,
            `Price held for ${Math.round(PRICE_LOCK_MS / 1000)}s while you complete booking`,
        ].map((reason) => `<div>${reason}</div>`).join('');
        pricingExplainer.style.display = 'block';
    } catch (err) {
        latestQuote = null;
        lockedQuote = null;
        quoteLockKey = null;
        quoteLockUntil = 0;
        modalRate.textContent = 'Price unavailable for selected slot';
        pricingExplainer.style.display = 'none';
    }
}

async function refreshUserUpcomingReservations() {
    const driver = bookDriver.value.trim();
    if (!driver) {
        userUpcoming.style.display = 'none';
        userUpcoming.innerHTML = '';
        return;
    }

    try {
        const res = await fetch(`/api/reservations?status=pending&driver_id=${encodeURIComponent(driver)}`);
        if (!res.ok) {
            throw new Error('Unable to load upcoming reservations');
        }

        const items = await res.json();
        const now = new Date();
        const upcoming = items
            .map((r) => ({ ...r, start: new Date(r.start_time), end: new Date(r.end_time) }))
            .filter((r) => r.start > now)
            .sort((a, b) => a.start - b.start);

        if (!upcoming.length) {
            userUpcoming.innerHTML = '<strong>Upcoming reservations:</strong> None';
            userUpcoming.style.display = 'block';
            return;
        }

        const rows = upcoming
            .map((r) => `<li>Spot ${r.spot_id}: ${formatLocalDate(r.start)} to ${formatLocalDate(r.end)}</li>`)
            .join('');

        userUpcoming.innerHTML = `<strong>Upcoming reservations:</strong><ul>${rows}</ul>`;
        userUpcoming.style.display = 'block';
    } catch {
        userUpcoming.innerHTML = '<strong>Upcoming reservations:</strong> Unable to load';
        userUpcoming.style.display = 'block';
    }
}

function renderConfirmation(reservation, start, end) {
    const durationMinutes = Math.round((end - start) / 60000);
    const durationText = durationMinutes >= 60
        ? `${(durationMinutes / 60).toFixed(durationMinutes % 60 === 0 ? 0 : 1)} hour(s)`
        : `${durationMinutes} minutes`;
    const total = latestQuote ? latestQuote.estimated_total : null;

    bookForm.style.display = 'none';
    confirmationPanel.style.display = 'block';
    confirmationPanel.innerHTML = `
        <h3>Reservation Confirmed</h3>
        <div><strong>Reservation ID:</strong> #${reservation.id}</div>
        <div><strong>Start:</strong> ${formatLocalDate(start)}</div>
        <div><strong>End:</strong> ${formatLocalDate(end)}</div>
        <div><strong>Duration:</strong> ${durationText}</div>
        <div><strong>Total Price:</strong> ${total !== null ? `$${total.toFixed(2)}` : 'Calculated at completion'}</div>
        <div class="confirmation-note">Your booking has been saved successfully.</div>
    `;

    showMsg('success', 'Reservation created successfully.');
}

function validateSelection(start, end) {
    if (!start || !end) {
        return 'Please select both start and end slots.';
    }

    const nowHourFloor = floorToHour(new Date());
    if (start < nowHourFloor) {
        return 'Start time cannot be before the current hour.';
    }

    if (end <= start) {
        return 'End time must be after start time.';
    }

    const durationMinutes = (end - start) / 60000;
    if (durationMinutes < MIN_BOOKING_MINUTES) {
        return `Minimum booking duration is ${MIN_BOOKING_MINUTES} minutes.`;
    }
    if (durationMinutes > MAX_BOOKING_HOURS * 60) {
        return `Maximum booking duration is ${MAX_BOOKING_HOURS} hours.`;
    }

    if (currentSpot && !isRangeFree(currentSpot.id, start, end)) {
        return 'Selected time range overlaps an existing reservation.';
    }
    return null;
}

function isRangeFree(spotId, start, end) {
    const list = reservationsBySpot[spotId] || [];
    return !list.some((r) => r.start < end && r.end > start);
}

function estimateSlotPrice(start) {
    if (!currentPricingRule) {
        return 0;
    }

    const base = Number(currentPricingRule.base_rate || 0);
    const peakMultiplier = Number(currentPricingRule.peak_multiplier || 1);
    const demand = estimatedDemandRatio(start);
    const demandMultiplier = smoothDemandMultiplier(demand);
    const isPeak = isPeakHourLocal(start);
    const hourly = base * (isPeak ? peakMultiplier : 1) * demandMultiplier;
    return hourly * 0.5;
}

function estimatedDemandRatio(pointInTime) {
    const occupied = new Set();
    const startsSoon = new Set();

    allReservations.forEach((r) => {
        if (r.start <= pointInTime && pointInTime < r.end) {
            occupied.add(r.spot_id);
        }
        const soonEnd = addMinutes(pointInTime, PROJECTION_LOOKAHEAD_HOURS * 60);
        if (pointInTime <= r.start && r.start < soonEnd) {
            startsSoon.add(r.spot_id);
        }
    });

    const total = allActiveSpotIds.size || 1;
    const overlapRatio = occupied.size / total;
    const startsSoonRatio = startsSoon.size / total;
    return Math.min((0.85 * overlapRatio) + (0.15 * startsSoonRatio), 1);
}

function smoothDemandMultiplier(demandRatio) {
    const ratio = Math.max(0, Math.min(1, demandRatio));
    const minSig = 1 / (1 + Math.exp(-DEMAND_SIGMOID_STEEPNESS * (0 - DEMAND_MIDPOINT)));
    const maxSig = 1 / (1 + Math.exp(-DEMAND_SIGMOID_STEEPNESS * (1 - DEMAND_MIDPOINT)));
    const curSig = 1 / (1 + Math.exp(-DEMAND_SIGMOID_STEEPNESS * (ratio - DEMAND_MIDPOINT)));
    const normalized = maxSig > minSig ? (curSig - minSig) / (maxSig - minSig) : 0;
    return 1 + (MAX_DEMAND_EXTRA * normalized);
}

function isPeakHourLocal(date) {
    const hour = date.getHours();
    return hour >= 13 && hour < 20;
}

function floorToHour(date) {
    const d = new Date(date);
    d.setMinutes(0, 0, 0);
    return d;
}

function addMinutes(date, minutes) {
    return new Date(date.getTime() + minutes * 60000);
}

function parseSlotValue(value) {
    if (!value) {
        return null;
    }
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
}

function formatSlotLabel(date) {
    return new Date(date).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function formatLocalDate(date) {
    return new Date(date).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function showMsg(type, text) {
    modalMsg.className = `modal-message ${type}`;
    modalMsg.textContent = text;
    modalMsg.style.display = 'block';
}

loadFloor();
setInterval(loadFloor, 5000);
