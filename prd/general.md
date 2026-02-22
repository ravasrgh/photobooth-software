 Kiosk-Mode Web-Based Photobooth Application

---

## Project Overview

A **full-screen, kiosk-mode web-based photobooth application** intended for **touchscreen kiosks connected to a camera and printer**. The system must operate **unattended**, be **touch-first**, and automatically reset between users.

The experience should replicate a physical photobooth:

**Attract Screen → Capture Setup → Countdown → Auto Capture → Frame Layout → Frame Customization → Preview → Print Result → Auto Reset**

The visual style must match the provided reference: **cute, pastel, playful, retro-kawaii**, featuring rounded UI, sticker-style decorations, soft shadows, and cheerful typography.

---

## Core Kiosk Constraints (Global Rules)

- Full-screen only (no browser chrome)
- Touch-first interaction model
- Minimum 48px touch targets
- No keyboard or mouse dependency
- Automatic progression where possible
- Inactivity timeout on all screens
- Automatic session reset after completion
- No user authentication
- Fail-safe recovery for camera and printer errors

---

## Global Design Language

### Visual Style
- Pastel palette (pink, cream, teal, yellow, lavender)
- High-contrast elements for visibility at distance
- Rounded cards, buttons, and previews
- Sticker-style decorative elements (flowers, stars, smileys)
- Large, bubbly display typography
- Clean, readable sans-serif body text

### Interaction Style
- Single-tap interactions only
- Clear press feedback (scale, glow)
- Soft animated transitions between screens
- Countdown and capture animations
- Visual-first feedback (audio optional)

---

## Kiosk User Flow & Screen Specifications

---

## 1. Attract / Idle Screen

### Purpose
Attract passersby and invite interaction.

### Layout
- Full-screen looping animation
- Pastel checkerboard background
- Floating decorative stickers
- Large central CTA

### Content
- Headline: **“Tap to Start!”**
- Subtext: “Take cute photos instantly”

### Behavior
- Tap anywhere to begin
- Auto-loop animation when idle
- No navigation or system UI visible

---

## 2. Capture Setup Screen

### Purpose
Prepare the user quickly with minimal choices.

### Layout
- Centered vertical card
- Large numeric photo count indicator
- One primary action button

### Content
- Title: **“Get Ready!”**
- Photo count (admin-configured)
- Button: **“Start Photo Session”**

### Behavior
- Auto-advance after short idle timeout
- No advanced settings exposed

---

## 3. Countdown Screen

### Purpose
Ensure user readiness before each capture.

### Layout
- Full-screen live camera preview
- Large animated countdown numerals (3 → 2 → 1)

### Content
- Animated numbers
- Encouraging microcopy (e.g., “Smile!”)

### Behavior
- No user controls
- Automatic progression
- Camera shutter animation on capture

---

## 4. Camera Capture Screen (Auto-Capture)

### Purpose
Fully automated photo capture experience.

### Layout
- Rounded live camera feed
- Progress indicator (e.g., dots or “Photo 2 of 4”)

### Content
- Friendly guidance text (“Hold still!”)

### Behavior
- Automatic capture cycles
- No manual shutter button
- Retake disabled or admin-controlled
- Session advances automatically

---

## 5. Frame Layout Selection Screen

### Purpose
Enable fast layout selection with minimal cognitive load.

### Layout
- Grid of large selectable layout cards

### Options
- Photo strip
- 2×2 grid
- Single-image layout

### Behavior
- One-tap selection
- Auto-advance after selection
- Default auto-selected if idle

---

## 6. Frame Customization Screen

### Purpose
Allow quick personalization without slowing throughput.

### Layout
- Left: Large live preview
- Right: Large icon-based controls

### Customization Options (Admin-Limited)
- Frame color presets
- Sticker presets (tap to add)
- Optional locked event branding

### Behavior
- Tap-to-apply only
- No precision dragging required
- Auto-advance after idle timeout

---

## 7. Preview & Confirmation Screen

### Purpose
Confirm output before printing.

### Layout
- Large centered framed photo
- Two oversized action buttons

### Buttons
- **Print Photo** (Primary)
- **Retake** (Secondary, optional)

### Behavior
- Auto-print after idle timeout (optional)
- Clear visual confirmation
- No deep navigation paths

---

## 8. Print Result Screen

### Purpose
Provide clear feedback during physical printing.

### Layout
- Full-screen celebratory background
- Centered print status card
- Animated printer illustration

### Content
- Title: **“Printing…”**
- Subtext: “Your photo is on the way!”
- Progress indicator (steps or bar)

### Behavior
- Print starts automatically
- User input disabled during printing
- Success animation on completion
- Message: “Please take your photo below”

### Error Handling
- Friendly error message if printer fails
- Auto-retry or skip-print option
- No technical jargon shown to users

---

## 9. Session Complete / Auto Reset Screen

### Purpose
End the session cleanly and prepare for the next user.

### Layout
- Thank-you message
- Light celebratory animation

### Content
- “Thank you!”
- “Get ready for the next guest”

### Behavior
- Auto-reset after short countdown (e.g., 5 seconds)
- Clears all session data
- Returns to Attract Screen

---

## Admin-Only (Hidden) Considerations

- Camera selection
- Printer configuration
- Photo count per session
- Idle timeout durations
- Default layouts and themes
- Event branding lock
- Maintenance / debug mode

*(Admin interfaces are not visible in kiosk mode.)*

---

## Accessibility & Environment Considerations

- Large fonts for distance viewing
- High-contrast buttons
- Clear visual success and error states
- No reliance on audio cues alone
- Designed for bright, public environments

---

## Google Stitch Output Expectations

- Full-screen kiosk-ready layouts
- Touch-optimized components
- Clear state transitions
- Resilient UX for hardware failures
- Modular, reusable UI components
