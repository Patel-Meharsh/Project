import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

/* ─────────────────────────────────────────────────────────────────
   TOUR STEP DEFINITIONS
   style: 'spotlight'  → dims page, cutout on element, tooltip arrow
          'tooltip'    → no dim, floating tooltip arrow on element
          'modal'      → centered floating card, no target
─────────────────────────────────────────────────────────────────── */
const STEPS = [
  {
    id:     'welcome',
    style:  'modal',
    nav:    '/',
    title:  'Welcome to Gateway OpsHub 👋',
    body:   "You're 60 seconds away from knowing everything you need. This tour will walk you through the key screens — skip or replay it anytime from your profile.",
    emoji:  '🏢',
    cta:    'Start the tour →',
    skip:   true,
  },
  {
    id:      'dashboard',
    style:   'spotlight',
    nav:     '/',
    target:  '.kpi-strip',
    place:   'bottom',
    title:   'Your Command Centre',
    body:    'These cards update live. Pending PRs, open orders, items below reorder level, and total stock value — your day starts here.',
  },
  {
    id:      'dashboard-actions',
    style:   'tooltip',
    nav:     '/',
    target:  '.dash-nav-card',
    place:   'top',
    title:   'Quick Actions',
    body:    'Jump straight into any task from these shortcuts. Raise a PR, record a GRN, or issue items — one click from the dashboard.',
  },
  {
    id:      'inventory',
    style:   'spotlight',
    nav:     '/inventory',
    target:  '.table-wrap',
    place:   'top',
    title:   'Stock Register',
    body:    'Every item across every location, live. Green means healthy stock. Red means you\'re below reorder level and need to act.',
  },
  {
    id:      'issuance-nav',
    style:   'tooltip',
    nav:     '/inventory',
    target:  '#nav-issuance',
    place:   'right',
    title:   'Issuance Log',
    body:    'This is where you record items going out — to departments, locations or staff. Click it to navigate there.',
  },
  {
    id:      'issuance',
    style:   'spotlight',
    nav:     '/issuance',
    target:  '.topbar',
    place:   'bottom',
    title:   'Record an Issuance',
    body:    'Hit "+ Issue Items" and pick the item, quantity, and who it\'s going to. The stock register updates automatically.',
  },
  {
    id:      'pr',
    style:   'spotlight',
    nav:     '/procurement/pr',
    target:  '.topbar',
    place:   'bottom',
    title:   'Raise a Purchase Request',
    body:    'Need something restocked? Raise a PR here. Choose priority — Urgent, High, Normal or Low. It goes to your approver automatically.',
  },
  {
    id:      'pr-filters',
    style:   'tooltip',
    nav:     '/procurement/pr',
    target:  '.filter-tabs, .tab-filters, .table-header',
    place:   'bottom',
    title:   'Filter by Status',
    body:    'Use the status pills to see Draft, Submitted, Approved or Rejected requests at a glance. Your team\'s full request history is always here.',
  },
  {
    id:      'items',
    style:   'spotlight',
    nav:     '/masters/items',
    target:  '.table-wrap',
    place:   'top',
    title:   'Item Catalogue',
    body:    'Every product the system knows about. Browse by category, check unit rates and reorder levels. Use the search to find anything instantly.',
  },
  {
    id:      'budget',
    style:   'modal',
    nav:     '/budget',
    title:   'Budget & Analytics',
    body:    'See how spend compares to budget — by item, by location, by month. The variance tab turns red when something\'s over budget.',
    emoji:   '📊',
    cta:     'Almost done →',
    skip:    false,
  },
  {
    id:      'profile',
    style:   'tooltip',
    nav:     '/budget',
    target:  '.sidebar > div:last-child',
    place:   'right',
    title:   'Your Profile',
    body:    'Click your name at the bottom of the sidebar to update your details, change your avatar colour, or replay this tour.',
  },
  {
    id:      'done',
    style:   'modal',
    nav:     null,
    title:   "You\'re all set! 🎉",
    body:    "That's the full picture. If you ever get stuck, the ? icons on each page give you contextual help. Happy inventory managing.",
    emoji:   '🚀',
    cta:     'Start exploring',
    skip:    false,
  },
]

/* ── Storage helpers ─────────────────────────────────────────────── */
const key    = (uid) => `gg_tour_${uid}`
export const markTourDone      = (uid) => localStorage.setItem(key(uid), '1')
export const resetTour         = (uid) => localStorage.removeItem(key(uid))
export const hasTourBeenSeen   = (uid) => !!localStorage.getItem(key(uid))

/* ── DOM helpers ─────────────────────────────────────────────────── */
const PAD = 10
function getEl(sel) {
  if (!sel) return null
  for (const s of sel.split(',')) {
    const el = document.querySelector(s.trim())
    if (el) return el
  }
  return null
}
function getRect(sel) {
  const el = getEl(sel)
  return el ? el.getBoundingClientRect() : null
}

/* ── Tooltip arrow ───────────────────────────────────────────────── */
function Arrow({ place, color = 'white' }) {
  const s = { position: 'absolute', width: 0, height: 0, borderStyle: 'solid' }
  if (place === 'bottom') return <div style={{ ...s, top: -9, left: 28, borderWidth: '0 9px 9px', borderColor: `transparent transparent ${color}` }} />
  if (place === 'top')    return <div style={{ ...s, bottom: -9, left: 28, borderWidth: '9px 9px 0', borderColor: `${color} transparent transparent` }} />
  if (place === 'right')  return <div style={{ ...s, left: -9, top: 22, borderWidth: '9px 9px 9px 0', borderColor: `transparent ${color} transparent transparent` }} />
  if (place === 'left')   return <div style={{ ...s, right: -9, top: 22, borderWidth: '9px 0 9px 9px', borderColor: `transparent transparent transparent ${color}` }} />
  return null
}

/* ── Position tooltip relative to target rect ───────────────────── */
function tipPos(rect, place) {
  if (!rect) return { top: 80, left: 80 }
  const W = 310, H = 200
  const vw = window.innerWidth, vh = window.innerHeight
  const sx = rect.left - PAD, sy = rect.top - PAD
  const sw = rect.width + PAD * 2, sh = rect.height + PAD * 2
  const clampX = (x) => Math.min(Math.max(x, 12), vw - W - 12)
  const clampY = (y) => Math.min(Math.max(y, 12), vh - H - 12)
  if (place === 'bottom') return { top: sy + sh + 14, left: clampX(sx) }
  if (place === 'top')    return { top: clampY(sy - H - 14), left: clampX(sx) }
  if (place === 'right')  return { top: clampY(sy), left: Math.min(sx + sw + 14, vw - W - 12) }
  if (place === 'left')   return { top: clampY(sy), left: Math.max(sx - W - 14, 12) }
  return { top: clampY(sy + sh + 14), left: clampX(sx) }
}

/* ── Progress dots ───────────────────────────────────────────────── */
function Dots({ current, total }) {
  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} style={{
          height: 4, borderRadius: 2, transition: 'all 0.3s ease',
          width: i === current ? 20 : 6,
          background: i < current ? '#f0a500' : i === current ? '#f0a500' : '#e2e8f0',
          opacity: i > current ? 0.5 : 1,
        }} />
      ))}
    </div>
  )
}

/* ── Nav buttons shared ──────────────────────────────────────────── */
function NavRow({ step, total, onPrev, onNext, onSkip, nextLabel, dark }) {
  const txt  = dark ? 'rgba(255,255,255,0.4)' : '#94a3b8'
  const txtH = dark ? 'rgba(255,255,255,0.7)' : '#64748b'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {step > 1 && (
        <button onClick={onPrev}
          style={{ padding: '9px 14px', borderRadius: 10, border: `1px solid ${dark ? 'rgba(255,255,255,0.15)' : '#e2e8f0'}`, background: 'transparent', cursor: 'pointer', fontWeight: 600, fontSize: 13, color: txtH, transition: 'all 0.15s' }}>
          ←
        </button>
      )}
      <button onClick={onSkip}
        style={{ padding: '9px 12px', borderRadius: 10, border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 12.5, color: txt, transition: 'color 0.15s' }}
        onMouseEnter={e => e.target.style.color = txtH} onMouseLeave={e => e.target.style.color = txt}>
        Skip tour
      </button>
      <button onClick={onNext}
        style={{ flex: 1, padding: '10px 18px', borderRadius: 10, border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: 13.5, color: 'white', background: 'linear-gradient(135deg,#f0a500,#e85d04)', boxShadow: '0 4px 14px rgba(240,165,0,0.35)', transition: 'transform 0.15s' }}
        onMouseEnter={e => e.target.style.transform = 'translateY(-1px)'}
        onMouseLeave={e => e.target.style.transform = ''}>
        {nextLabel || 'Next →'}
      </button>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════
   MAIN TOUR COMPONENT
══════════════════════════════════════════════════════════════════ */
export default function Tour({ user, onDone }) {
  const [idx, setIdx]     = useState(0)
  const [rect, setRect]   = useState(null)
  const [visible, setVisible] = useState(false)
  const navigate  = useNavigate()
  const location  = useLocation()
  const raf       = useRef(null)

  const step  = STEPS[idx]
  const isLast = idx === STEPS.length - 1
  const total  = STEPS.length

  /* Navigate + measure */
  const applyStep = useCallback((i) => {
    const s = STEPS[i]
    setVisible(false)
    const doMeasure = () => {
      const r = getRect(s.target)
      setRect(r)
      // Scroll target into view
      if (s.target) {
        const el = getEl(s.target)
        if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      }
      raf.current = requestAnimationFrame(() => {
        setVisible(true)
      })
    }
    if (s.nav && location.pathname !== s.nav) {
      navigate(s.nav)
      setTimeout(doMeasure, 380)
    } else {
      setTimeout(doMeasure, 80)
    }
  }, [navigate, location.pathname])

  useEffect(() => { applyStep(idx) }, [idx])

  useEffect(() => {
    const handler = () => { if (step.target) setRect(getRect(step.target)) }
    window.addEventListener('resize', handler)
    return () => { window.removeEventListener('resize', handler); if (raf.current) cancelAnimationFrame(raf.current) }
  }, [step.target])

  const next = () => { if (isLast) { markTourDone(user?.id); onDone() } else setIdx(i => i + 1) }
  const prev = () => { if (idx > 0) setIdx(i => i - 1) }
  const skip = () => { markTourDone(user?.id); onDone() }

  if (!visible) return null

  const pos   = tipPos(rect, step.place)
  const arrowFlip = { bottom: 'top', top: 'bottom', right: 'left', left: 'right' }

  /* ── MODAL style ─────────────────────────────────────────────── */
  if (step.style === 'modal') {
    return (
      <div style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(10,12,28,0.80)', backdropFilter: 'blur(6px)', animation: 'tourFadeIn 0.25s ease both' }}>
        <div style={{ width: 460, background: 'white', borderRadius: 28, overflow: 'hidden', boxShadow: '0 40px 100px rgba(0,0,0,0.4)', animation: 'tourSlideUp 0.35s cubic-bezier(0.34,1.56,0.64,1) both' }}>
          {/* Coloured header band */}
          <div style={{ padding: '36px 36px 28px', background: 'linear-gradient(135deg,#0d0f1a,#1a1f35)', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', top: -40, right: -40, width: 180, height: 180, borderRadius: '50%', background: 'radial-gradient(circle,rgba(240,165,0,0.15),transparent 70%)' }} />
            <div style={{ width: 60, height: 60, borderRadius: 18, background: 'linear-gradient(135deg,#f0a500,#e85d04)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 26, marginBottom: 18, boxShadow: '0 8px 24px rgba(240,165,0,0.4)' }}>
              {step.emoji || '✨'}
            </div>
            <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 700, color: 'white', lineHeight: 1.25, marginBottom: 10 }}>{step.title}</div>
            <div style={{ fontSize: 14.5, color: 'rgba(255,255,255,0.55)', lineHeight: 1.65 }}>{step.body}</div>
          </div>

          {/* Footer */}
          <div style={{ padding: '20px 36px 28px', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Dots current={idx} total={total} />
            <div style={{ display: 'flex', gap: 10 }}>
              {step.skip !== false && (
                <button onClick={skip} style={{ flex: 1, padding: '12px', borderRadius: 12, border: '1px solid #e2e8f0', background: 'white', cursor: 'pointer', fontWeight: 600, fontSize: 14, color: '#64748b' }}>Skip tour</button>
              )}
              <button onClick={next} style={{ flex: 2, padding: '12px', borderRadius: 12, border: 'none', background: 'linear-gradient(135deg,#f0a500,#e85d04)', color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: 15, boxShadow: '0 8px 24px rgba(240,165,0,0.35)' }}>
                {step.cta || (isLast ? 'Done!' : 'Next →')}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  /* ── SPOTLIGHT style ─────────────────────────────────────────── */
  if (step.style === 'spotlight') {
    const sx = rect ? rect.left - PAD : 0
    const sy = rect ? rect.top  - PAD : 0
    const sw = rect ? rect.width  + PAD * 2 : 0
    const sh = rect ? rect.height + PAD * 2 : 0

    return (
      <div style={{ position: 'fixed', inset: 0, zIndex: 9999, pointerEvents: 'none' }}>
        {/* SVG dim + cutout */}
        {rect ? (
          <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'auto' }}>
            <defs>
              <mask id="spmask">
                <rect width="100%" height="100%" fill="white" />
                <rect x={sx} y={sy} width={sw} height={sh} rx={10} fill="black" />
              </mask>
            </defs>
            <rect width="100%" height="100%" fill="rgba(8,10,24,0.75)" mask="url(#spmask)" onClick={next} style={{ cursor: 'pointer' }} />
            {/* Spotlight glow ring */}
            <rect x={sx - 1.5} y={sy - 1.5} width={sw + 3} height={sh + 3} rx={11.5} fill="none" stroke="#f0a500" strokeWidth={2} opacity={0.7} />
            <rect x={sx - 5} y={sy - 5} width={sw + 10} height={sh + 10} rx={15} fill="none" stroke="#f0a500" strokeWidth={0.5} opacity={0.25} />
          </svg>
        ) : (
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(8,10,24,0.75)', pointerEvents: 'auto' }} onClick={next} />
        )}

        {/* Tooltip */}
        <div style={{ position: 'absolute', ...pos, width: 310, pointerEvents: 'auto', animation: 'tourSlideUp 0.3s cubic-bezier(0.34,1.56,0.64,1) both' }}>
          <Arrow place={arrowFlip[step.place]} />
          <div style={{ background: 'white', borderRadius: 18, padding: '22px 22px 18px', boxShadow: '0 24px 60px rgba(0,0,0,0.28)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <Dots current={idx} total={total} />
              <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>{idx + 1} / {total}</span>
            </div>
            <div style={{ fontFamily: "'Fraunces',serif", fontSize: 16, fontWeight: 700, color: '#0d0f1a', marginBottom: 7, lineHeight: 1.3 }}>{step.title}</div>
            <div style={{ fontSize: 13, color: '#64748b', lineHeight: 1.6, marginBottom: 16 }}>{step.body}</div>
            <NavRow step={idx} total={total} onPrev={prev} onNext={next} onSkip={skip} nextLabel={isLast ? 'Done!' : 'Next →'} />
          </div>
        </div>

        {/* Click-anywhere hint */}
        <div style={{ position: 'absolute', bottom: 20, left: '50%', transform: 'translateX(-50%)', fontSize: 12, color: 'rgba(255,255,255,0.35)', pointerEvents: 'none', whiteSpace: 'nowrap' }}>
          Click anywhere to advance · <kbd style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: 4 }}>Esc</kbd> to skip
        </div>
      </div>
    )
  }

  /* ── TOOLTIP style ───────────────────────────────────────────── */
  if (step.style === 'tooltip') {
    return (
      <div style={{ position: 'fixed', inset: 0, zIndex: 9999, pointerEvents: 'none' }}>
        {/* No overlay — content stays interactive */}

        {/* Pulsing beacon on target */}
        {rect && (
          <div style={{ position: 'absolute', left: rect.left + rect.width / 2 - 8, top: rect.top + rect.height / 2 - 8, width: 16, height: 16, pointerEvents: 'none' }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: '#f0a500', opacity: 0.9, animation: 'tourBeacon 1.4s ease-out infinite' }} />
            <div style={{ position: 'absolute', inset: 3, borderRadius: '50%', background: '#f0a500' }} />
          </div>
        )}

        {/* Floating tooltip — dark glass style */}
        <div style={{ position: 'absolute', ...pos, width: 300, pointerEvents: 'auto', animation: 'tourSlideUp 0.3s cubic-bezier(0.34,1.56,0.64,1) both' }}>
          <Arrow place={arrowFlip[step.place]} color="#1e2538" />
          <div style={{ background: 'linear-gradient(135deg,#1e2538,#0d0f1a)', borderRadius: 18, padding: '20px 20px 16px', boxShadow: '0 20px 50px rgba(0,0,0,0.45)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <Dots current={idx} total={total} />
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', fontWeight: 500 }}>{idx + 1} / {total}</span>
            </div>
            <div style={{ fontFamily: "'Fraunces',serif", fontSize: 15.5, fontWeight: 700, color: 'white', marginBottom: 7, lineHeight: 1.3 }}>{step.title}</div>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.55)', lineHeight: 1.6, marginBottom: 16 }}>{step.body}</div>
            <NavRow step={idx} total={total} onPrev={prev} onNext={next} onSkip={skip} nextLabel={isLast ? 'Done!' : 'Next →'} dark />
          </div>
        </div>
      </div>
    )
  }

  return null
}
