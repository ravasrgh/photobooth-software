/* ── Photobooth Prototype — Frontend Logic ───────────────────── */

const API = {
  status:              () => fetch('/api/status').then(r => r.json()),
  sessionStart:        () => fetch('/api/session/start', { method: 'POST' }).then(r => r.json()),
  sessionCancel:       () => fetch('/api/session/cancel', { method: 'POST' }).then(r => r.json()),
  sessionComplete:     () => fetch('/api/session/complete', { method: 'POST' }).then(r => r.json()),
  onboardingComplete:  () => fetch('/api/onboarding/complete', { method: 'POST' }).then(r => r.json()),
  paymentInitiate: (m) => fetch('/api/payment/initiate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method: m }),
  }).then(r => r.json()),
  captureReady:        () => fetch('/api/capture/ready', { method: 'POST' }).then(r => r.json()),
  captureTake: (img) => fetch('/api/capture/take', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_data: img || null }),
  }).then(r => r.json()),
  customizeLayout: (id) => fetch('/api/customize/layout', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layout_id: id }),
  }).then(r => r.json()),
  customizeDesign: (id) => fetch('/api/customize/design', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ design_id: id }),
  }).then(r => r.json()),
  customizeFilter: (idx, fid) => fetch('/api/customize/filter', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ photo_index: idx, filter_id: fid }),
  }).then(r => r.json()),
  customizeConfirm:    () => fetch('/api/customize/confirm', { method: 'POST' }).then(r => r.json()),
  previewBack:         () => fetch('/api/preview/back', { method: 'POST' }).then(r => r.json()),
  printRequest:        () => fetch('/api/print/request', { method: 'POST' }).then(r => r.json()),
  captureRetake: (idx, img) => fetch('/api/capture/retake', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ photo_index: idx, image_data: img || null }),
  }).then(r => r.json()),
};

/* ── Constants ────────────────────────────────────────────────── */
const FILTERS = {
  original: 'none',
  bw:      'grayscale(100%)',
  sepia:   'sepia(80%) saturate(120%)',
  warm:    'saturate(130%) brightness(105%) hue-rotate(-10deg)',
  cool:    'saturate(110%) brightness(105%) hue-rotate(15deg)',
  vintage: 'sepia(30%) contrast(110%) brightness(90%) saturate(85%)',
};

const LAYOUTS = [
  { id: 'strip_vertical',   label: 'Vertical Strip' },
  { id: 'strip_horizontal', label: 'Horizontal Strip' },
  { id: 'grid_2x2',         label: '2x2 Grid' },
  { id: 'collage_1_3',      label: '1 Large + 3 Small' },
];

const DESIGNS = [
  { id: 'classic_white', label: 'Classic White' },
  { id: 'elegant_black', label: 'Elegant Black' },
  { id: 'soft_pink',     label: 'Soft Pink' },
  { id: 'ocean_blue',    label: 'Ocean Blue' },
];

/* ── State ────────────────────────────────────────────────────── */
const STATE_SCREEN_MAP = {
  IDLE:             'screen-attract',
  ONBOARDING:       'screen-onboarding',
  AWAITING_PAYMENT: 'screen-payment',
  CAPTURE_SETUP:    'screen-capture-setup',
  COUNTDOWN:        'screen-capture',
  CAPTURING:        'screen-capture',
  PROCESSING:       'screen-capture',
  CUSTOMIZATION:    'screen-customization',
  PREVIEW:          'screen-preview',
  PRINTING:         'screen-printing',
  COMPLETE:         'screen-printing',
};

const app = {
  state: 'IDLE',
  photos: [],
  photosTarget: 4,
  photoIndex: 0,
  onboardingStep: 0,
  selectedPhoto: null,
  layoutId: 'strip_vertical',
  designId: 'classic_white',
  cameraAvailable: false,
  previewUrl: null,
  webcamStream: null,
  polling: null,
  retaking: false,
  sessionTimer: null,
  sessionTimerSeconds: 60,

  /* ── Screen management ──────────────────────────────────────── */
  showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
  },

  updateState(newState) {
    this.state = newState;
    const screenId = STATE_SCREEN_MAP[newState] || 'screen-attract';
    this.showScreen(screenId);
  },

  /* ── Session ────────────────────────────────────────────────── */
  async startSession() {
    const res = await API.sessionStart();
    this.photosTarget = res.photos_target || 4;
    this.photos = [];
    this.photoIndex = 0;
    this.onboardingStep = 0;
    this.selectedPhoto = null;
    // Clear stale thumbnails from previous session
    const thumbs = document.getElementById('capture-thumbs');
    if (thumbs) thumbs.innerHTML = '';
    this.resetOnboarding();
    this.updateState(res.state);
  },

  async cancelSession() {
    this.stopPolling();
    this.stopWebcam();
    await API.sessionCancel();
    this.updateState('IDLE');
  },

  /* ── Onboarding ─────────────────────────────────────────────── */
  resetOnboarding() {
    this.onboardingStep = 0;
    this.renderOnboardingStep();
  },

  renderOnboardingStep() {
    const cards = document.querySelectorAll('.onboarding-card');
    const dots = document.querySelectorAll('.dot');
    cards.forEach((c, i) => c.classList.toggle('active', i === this.onboardingStep));
    dots.forEach((d, i) => d.classList.toggle('active', i === this.onboardingStep));
    const btn = document.getElementById('btn-onboarding-next');
    btn.textContent = this.onboardingStep >= cards.length - 1 ? 'Get Started' : 'Next';
  },

  async nextOnboardingStep() {
    const total = document.querySelectorAll('.onboarding-card').length;
    if (this.onboardingStep < total - 1) {
      this.onboardingStep++;
      this.renderOnboardingStep();
    } else {
      this.skipOnboarding();
    }
  },

  async skipOnboarding() {
    const res = await API.onboardingComplete();
    this.updateState(res.state);
  },

  /* ── Payment ────────────────────────────────────────────────── */
  async selectPaymentMethod(method) {
    document.querySelectorAll('#screen-payment .tab').forEach((t, i) => {
      t.classList.toggle('active', (i === 0 && method === 'qris') || (i === 1 && method === 'voucher'));
    });
    document.getElementById('payment-status').textContent = 'Processing payment...';
    await API.paymentInitiate(method);
    this.startPaymentPolling();
  },

  startPaymentPolling() {
    this.stopPolling();
    this.polling = setInterval(async () => {
      const status = await API.status();
      if (status.state === 'CAPTURE_SETUP') {
        this.stopPolling();
        this.photos = status.photos || [];
        this.startCamera('preview');
        this.updateState('CAPTURE_SETUP');
      }
    }, 500);
  },

  stopPolling() {
    if (this.polling) { clearInterval(this.polling); this.polling = null; }
  },

  /* ── Camera / Webcam ────────────────────────────────────────── */
  async startCamera(mode) {
    // mode: 'preview' for setup, 'capture' for capturing
    const videoId = mode === 'preview' ? 'webcam-video' : 'capture-webcam';
    const mjpegId = mode === 'preview' ? 'mjpeg-preview' : 'capture-mjpeg';
    const placeholderId = 'preview-placeholder';

    // Check server for DSLR
    const status = await API.status();
    this.cameraAvailable = status.camera_available;
    this.previewUrl = status.preview_url;

    if (this.cameraAvailable && this.previewUrl) {
      // Use MJPEG from DSLR
      const mjpeg = document.getElementById(mjpegId);
      if (mjpeg) { mjpeg.src = this.previewUrl; mjpeg.style.display = 'block'; }
      const video = document.getElementById(videoId);
      if (video) video.style.display = 'none';
      const ph = document.getElementById(placeholderId);
      if (ph) ph.style.display = 'none';
    } else {
      // Webcam fallback
      try {
        if (!this.webcamStream) {
          this.webcamStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: 640, height: 480 }
          });
        }
        const video = document.getElementById(videoId);
        if (video) {
          video.srcObject = this.webcamStream;
          video.style.display = 'block';
        }
        const mjpeg = document.getElementById(mjpegId);
        if (mjpeg) mjpeg.style.display = 'none';
        const ph = document.getElementById(placeholderId);
        if (ph) ph.style.display = 'none';
      } catch (e) {
        console.warn('No webcam:', e);
        // Show placeholder
        const ph = document.getElementById(placeholderId);
        if (ph) ph.style.display = 'block';
      }
    }
  },

  captureWebcamFrame() {
    const video = document.getElementById('capture-webcam');
    if (!video || !video.srcObject) return null;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext('2d').drawImage(video, 0, 0);
    return canvas.toDataURL('image/jpeg', 0.9);
  },

  stopWebcam() {
    if (this.webcamStream) {
      this.webcamStream.getTracks().forEach(t => t.stop());
      this.webcamStream = null;
    }
  },

  /* ── Capture ────────────────────────────────────────────────── */
  async captureReady() {
    // Clear any stale thumbnails
    document.getElementById('capture-thumbs').innerHTML = '';
    await this.startCamera('capture');
    await API.captureReady();
    this.updateState('COUNTDOWN');
    this.runCaptureLoop();
  },

  async runCaptureLoop() {
    const remaining = this.photosTarget - this.photoIndex;
    for (let i = 0; i < remaining; i++) {
      document.getElementById('capture-progress').textContent =
        `Photo ${this.photoIndex + 1} of ${this.photosTarget}`;

      // Countdown 3-2-1
      await this.showCountdown(3);

      // Flash
      const flash = document.getElementById('capture-flash');
      flash.classList.add('active');
      setTimeout(() => flash.classList.remove('active'), 150);

      // Capture frame
      const imgData = this.cameraAvailable ? null : this.captureWebcamFrame();
      const res = await API.captureTake(imgData);

      this.photos = res.photos || [];
      this.photoIndex = res.photo_index;
      this.renderCaptureThumbs();

      if (res.state === 'CUSTOMIZATION') {
        this.stopWebcam();
        this.updateState('CUSTOMIZATION');
        this.initCustomization();
        return;
      }

      // Brief pause before next
      await this.sleep(1000);
    }
  },

  async showCountdown(from) {
    const overlay = document.getElementById('countdown-overlay');
    const num = document.getElementById('countdown-number');
    overlay.classList.add('visible');
    for (let i = from; i >= 1; i--) {
      num.textContent = i;
      await this.sleep(1000);
    }
    overlay.classList.remove('visible');
  },

  renderCaptureThumbs() {
    const el = document.getElementById('capture-thumbs');
    el.innerHTML = this.photos.map(p =>
      `<img src="${p.url}?t=${Date.now()}" alt="Photo ${p.index}">`
    ).join('');
  },

  /* ── Customization ──────────────────────────────────────────── */
  initCustomization() {
    this.selectedPhoto = null;
    this.renderCustomizePreview();
    this.renderLayoutOptions();
    this.renderDesignOptions();
    this.renderFilterOptions();
    this.showCustomizeTab('layout');
    // Reset retake button
    const retakeBtn = document.getElementById('btn-retake');
    if (retakeBtn) retakeBtn.classList.add('disabled');
  },

  renderCustomizePreview() {
    const el = document.getElementById('customize-preview');
    const layout = this.layoutId;
    let style = '';

    // Reset inline styles but keep class styles (overflow, etc.)
    const base = 'background:var(--surface);border-radius:var(--radius-lg);padding:12px;overflow-y:auto;overflow-x:hidden;';

    if (layout === 'grid_2x2') {
      el.style.cssText = base + 'display:grid;grid-template-columns:1fr 1fr;gap:6px;align-content:start;';
      style = 'width:100%;aspect-ratio:4/3;';
    } else if (layout === 'strip_horizontal') {
      el.style.cssText = base + 'display:flex;gap:6px;flex-wrap:nowrap;align-items:start;overflow-x:auto;';
      style = 'height:200px;aspect-ratio:4/3;flex-shrink:0;';
    } else if (layout === 'collage_1_3') {
      el.style.cssText = base + 'display:grid;grid-template-columns:2fr 1fr;grid-template-rows:repeat(3,minmax(0,1fr));gap:6px;';
    } else {
      // strip_vertical
      el.style.cssText = base + 'display:flex;flex-direction:column;flex-wrap:nowrap;gap:6px;align-items:center;';
      style = 'width:75%;max-width:260px;aspect-ratio:4/3;object-fit:cover;flex-shrink:0;';
    }

    el.innerHTML = this.photos.map((p, i) => {
      const filter = FILTERS[p.filter_id] || 'none';
      const selected = this.selectedPhoto === p.index ? 'selected' : '';
      let s = style;
      if (layout === 'collage_1_3') {
        s = i === 0
          ? 'grid-row:1/4;width:100%;height:100%;'
          : 'width:100%;aspect-ratio:4/3;';
      }
      return `<img src="${p.url}?t=${Date.now()}" alt="Photo ${p.index}"
        class="${selected}" style="${s}filter:${filter};"
        onclick="app.selectPhotoForFilter(${p.index})">`;
    }).join('');
  },

  selectPhotoForFilter(idx) {
    this.selectedPhoto = this.selectedPhoto === idx ? null : idx;
    this.renderCustomizePreview();
    const hint = document.getElementById('filter-hint');
    if (hint) hint.textContent = this.selectedPhoto
      ? `Filters for Photo ${this.selectedPhoto}`
      : 'Tap a photo above, then choose a filter';
    // Toggle retake button
    const retakeBtn = document.getElementById('btn-retake');
    if (retakeBtn) {
      if (this.selectedPhoto) {
        retakeBtn.classList.remove('disabled');
      } else {
        retakeBtn.classList.add('disabled');
      }
    }
  },

  /* ── Retake ───────────────────────────────────────────────────── */
  async retakePhoto() {
    if (!this.selectedPhoto) return;
    const idx = this.selectedPhoto;
    this.retaking = true;

    // Show capture screen with webcam
    this.showScreen('screen-capture');
    document.getElementById('capture-progress').textContent = `Retaking Photo ${idx}`;
    document.getElementById('capture-thumbs').innerHTML = '';
    await this.startCamera('capture');

    // Countdown
    await this.showCountdown(3);

    // Flash
    const flash = document.getElementById('capture-flash');
    flash.classList.add('active');
    setTimeout(() => flash.classList.remove('active'), 150);

    // Capture
    const imgData = this.cameraAvailable ? null : this.captureWebcamFrame();
    const res = await API.captureRetake(idx, imgData);

    // Update local photo list
    if (res.photos) this.photos = res.photos;

    this.stopWebcam();
    this.retaking = false;
    this.selectedPhoto = null;

    // Go back to customization
    this.showScreen('screen-customization');
    this.initCustomization();
  },

  renderLayoutOptions() {
    const el = document.getElementById('layout-options');
    el.innerHTML = LAYOUTS.map(l =>
      `<button class="option-card ${l.id === this.layoutId ? 'active' : ''}"
        onclick="app.setLayout('${l.id}')">${l.label}</button>`
    ).join('');
  },

  renderDesignOptions() {
    const el = document.getElementById('design-options');
    el.innerHTML = DESIGNS.map(d =>
      `<button class="option-card ${d.id === this.designId ? 'active' : ''}"
        onclick="app.setDesign('${d.id}')">${d.label}</button>`
    ).join('');
  },

  renderFilterOptions() {
    const el = document.getElementById('filter-options');
    el.innerHTML = Object.keys(FILTERS).map(f => {
      const label = f.charAt(0).toUpperCase() + f.slice(1);
      const current = this.selectedPhoto
        ? (this.photos.find(p => p.index === this.selectedPhoto)?.filter_id || 'original')
        : null;
      return `<button class="option-card ${f === current ? 'active' : ''}"
        onclick="app.setFilter('${f}')">${label}</button>`;
    }).join('');
  },

  showCustomizeTab(name) {
    ['layout', 'design', 'filters'].forEach(t => {
      document.getElementById('tab-' + t).style.display = t === name ? 'flex' : 'none';
    });
    document.querySelectorAll('#screen-customization .tab-bar .tab').forEach((t, i) => {
      t.classList.toggle('active',
        (i === 0 && name === 'layout') ||
        (i === 1 && name === 'design') ||
        (i === 2 && name === 'filters'));
    });
  },

  async setLayout(id) {
    this.layoutId = id;
    await API.customizeLayout(id);
    this.renderLayoutOptions();
    this.renderCustomizePreview();
  },

  async setDesign(id) {
    this.designId = id;
    await API.customizeDesign(id);
    this.renderDesignOptions();
  },

  async setFilter(id) {
    if (!this.selectedPhoto) return;
    await API.customizeFilter(this.selectedPhoto, id);
    const p = this.photos.find(x => x.index === this.selectedPhoto);
    if (p) p.filter_id = id;
    this.renderCustomizePreview();
    this.renderFilterOptions();
  },

  async confirmCustomization() {
    const res = await API.customizeConfirm();
    this.updateState(res.state);
    this.renderPrintPreview();
  },

  /* ── Print Preview ──────────────────────────────────────────── */
  renderPrintPreview() {
    const el = document.getElementById('preview-composite');
    el.innerHTML = this.photos.map(p => {
      const filter = FILTERS[p.filter_id] || 'none';
      return `<img src="${p.url}" style="width:120px;aspect-ratio:4/3;filter:${filter};" alt="Photo ${p.index}">`;
    }).join('');
  },

  async backToCustomize() {
    const res = await API.previewBack();
    this.updateState(res.state);
    this.initCustomization();
  },

  /* ── Print ──────────────────────────────────────────────────── */
  async requestPrint() {
    this.updateState('PRINTING');
    document.getElementById('print-title').textContent = 'Printing...';
    document.getElementById('screen-printing').classList.remove('done');
    const bar = document.getElementById('print-progress-bar');
    bar.style.width = '20%';
    setTimeout(() => bar.style.width = '60%', 400);

    const res = await API.printRequest();
    bar.style.width = '100%';
    document.getElementById('print-title').textContent = 'Your photos are ready!';

    // Start 60s session timer
    this.startSessionTimer();
  },

  /* ── Session Timer (60s on QR screen) ────────────────────────── */
  startSessionTimer() {
    this.clearSessionTimer();
    const screen = document.getElementById('screen-printing');
    screen.classList.add('done');
    let remaining = this.sessionTimerSeconds;
    const timerBar = document.getElementById('session-timer-bar');
    const timerText = document.getElementById('session-timer-text');
    timerBar.style.width = '100%';
    timerText.textContent = `Session ends in ${remaining}s`;

    // Tap to start new session
    const tapHandler = async (e) => {
      // Prevent double-firing
      screen.removeEventListener('click', tapHandler);
      this.clearSessionTimer();
      await API.sessionComplete();
      this._reset_session_local();
      this.updateState('IDLE');
      this.startSession();
    };
    screen.addEventListener('click', tapHandler);
    this._tapHandler = tapHandler;

    this.sessionTimer = setInterval(async () => {
      remaining--;
      const pct = (remaining / this.sessionTimerSeconds) * 100;
      timerBar.style.width = pct + '%';
      timerText.textContent = `Session ends in ${remaining}s`;
      if (remaining <= 0) {
        screen.removeEventListener('click', tapHandler);
        this.clearSessionTimer();
        await API.sessionComplete();
        this._reset_session_local();
        this.updateState('IDLE');
      }
    }, 1000);
  },

  clearSessionTimer() {
    if (this.sessionTimer) { clearInterval(this.sessionTimer); this.sessionTimer = null; }
    const screen = document.getElementById('screen-printing');
    if (this._tapHandler) {
      screen.removeEventListener('click', this._tapHandler);
      this._tapHandler = null;
    }
  },

  _reset_session_local() {
    this.photos = [];
    this.photoIndex = 0;
    this.selectedPhoto = null;
    this.layoutId = 'strip_vertical';
    this.designId = 'classic_white';
  },

  /* ── Utility ────────────────────────────────────────────────── */
  sleep(ms) { return new Promise(r => setTimeout(r, ms)); },
};

/* ── Init: check current state ────────────────────────────────── */
(async () => {
  const status = await API.status();
  app.cameraAvailable = status.camera_available;
  app.previewUrl = status.preview_url;
  app.updateState(status.state);
})();
