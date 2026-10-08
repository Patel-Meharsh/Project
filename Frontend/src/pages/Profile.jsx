import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../lib/AuthContext'
import { authApi, ROLES, canDo, validatePassword } from '../lib/auth'
import { PasswordInput } from './Login'
import Header from '../components/Header'
import { tourBus } from '../App'
import { resetTour, hasTourBeenSeen } from '../components/Tour'
import { Spinner } from '../components/UI'

/* -- Palette & constants ----------------------------------------------- */
const COLORS = [
  '#f0a500','#e85d04','#dc2626','#ec4899','#a855f7',
  '#8b5cf6','#3b82f6','#06b6d4','#10b981','#84cc16',
]
const DEPTS  = ['Admin','Housekeeping','Maintenance','Finance','HR','Operations','Security','Procurement','IT','Management']
const PATTERNS = ['initials','rings','grid','dots','wave']

/* -- Avatar SVG generator ---------------------------------------------- */
function AvatarGraphic({ user, size = 56, pattern = 'initials', onClick }) {
  const c = user?.avatar_color || '#f0a500'
  const c2 = shiftHue(c, 40)

  const colorKey = (c || '').replace('#','')  

  const ini = ((user?.full_name || 'U')
    .split(' ')
    .map(p => p[0])
    .slice(0,2)
    .join('')
    .toUpperCase()) || 'U'
  
    return (
    <div onClick={onClick} style={{
      width:size, height:size, borderRadius:'50%', flexShrink:0, cursor:onClick?'pointer':'default',
      position:'relative', overflow:'hidden',
      boxShadow:`0 0 0 3px ${c}30, 0 8px 32px ${c}35`,
      transition:'transform 0.2s, box-shadow 0.2s',
    }}
    onMouseEnter={e=>{ if(onClick){e.currentTarget.style.transform='scale(1.05)'; e.currentTarget.style.boxShadow=`0 0 0 3px ${c}60, 0 12px 40px ${c}50`} }}
    onMouseLeave={e=>{ e.currentTarget.style.transform=''; e.currentTarget.style.boxShadow=`0 0 0 3px ${c}30, 0 8px 32px ${c}35` }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id={`bg-${size}-${(colorKey).replace('#','')}`} cx="35%" cy="30%" r="80%">
            <stop offset="0%" stopColor={c2} />
            <stop offset="100%" stopColor={c} />
          </radialGradient>
          <clipPath id={`clip-${size}-${(colorKey).replace('#','')}`}><circle cx={size/2} cy={size/2} r={size/2} /></clipPath>
        </defs>
        <circle cx={size/2} cy={size/2} r={size/2} fill={`url(#bg-${size}-${(colorKey).replace('#','')})`} />
        {/* decorative pattern */}
        <g clipPath={`url(#clip-${size}-${(colorKey).replace('#','')})`} opacity="0.18">
          {[0,1,2,3].map(i=>(
            <circle key={i} cx={size*0.7} cy={size*(0.1+i*0.28)} r={size*(0.18+i*0.04)} fill="none" stroke="white" strokeWidth={size*0.025} />
          ))}
        </g>
        {/* shine */}
        <ellipse cx={size*0.38} cy={size*0.3} rx={size*0.22} ry={size*0.12} fill="white" opacity="0.15" transform={`rotate(-25,${size*0.38},${size*0.3})`} />
        {/* initials */}
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle"
          fill="white" fontSize={size*0.34} fontWeight="700"
          fontFamily="'Fraunces',serif" letterSpacing="-0.5">
          {ini}
        </text>
      </svg>
    </div>
  )
}

function shiftHue(hex, deg) {
  // simple hue-adjacent colour for gradient
  try {
    const r=parseInt(hex.slice(1,3),16), g=parseInt(hex.slice(3,5),16), b=parseInt(hex.slice(5,7),16)
    const mix = (a,b,t)=>Math.round(a*(1-t)+b*t)
    return `rgb(${mix(r,g,0.4)},${mix(g,b,0.4)},${mix(b,r,0.4)})`
  } catch { return hex }
}

function RoleBadge({ role, size='sm' }) {
  const r = ROLES[role] || ROLES.observer
  const sm = size==='sm'
  return (
    <span style={{ fontSize:sm?11:12.5, fontWeight:700, padding:sm?'3px 10px':'4px 14px', borderRadius:20,
      background:r.bg, color:r.color, border:`1px solid ${r.color}30`,
      textTransform:'uppercase', letterSpacing:'0.06em', whiteSpace:'nowrap' }}>{r.label}</span>
  )
}

/* -- Password strength bar --------------------------------------------- */
function PwStrength({ password }) {
  const { rules } = validatePassword(password||'')
  if (!password) return null
  return (
    <div style={{ marginTop:8, padding:'10px 14px', borderRadius:8, background:'#f8f9fc', border:'1px solid #edf0f7' }}>
      {rules.map(r=>(
        <div key={r.id} style={{ display:'flex', alignItems:'center', gap:8, marginBottom:r.id!=='special'?5:0 }}>
          <div style={{ width:15, height:15, borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
            background:r.ok?'#f0fdf4':'#f8f9fc', border:`1.5px solid ${r.ok?'#22c55e':'#d1d5db'}`, transition:'all 0.2s' }}>
            {r.ok&&<svg width="7" height="7" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5L8 3" stroke="#16a34a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
          </div>
          <span style={{ fontSize:12, color:r.ok?'#16a34a':'#94a3b8', transition:'color 0.2s' }}>{r.label}</span>
        </div>
      ))}
    </div>
  )
}

/* -- Light-mode password input ----------------------------------------- */
function LightPasswordInput({ value, onChange, placeholder }) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef(null)
  const toggle = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!visible) { setVisible(true); timerRef.current = setTimeout(()=>setVisible(false), 2000) }
    else setVisible(false)
  }
  return (
    <div style={{ position:'relative' }}>
      <input type={visible?'text':'password'} value={value} onChange={onChange} placeholder={placeholder||'••••••••'} className="input"
        style={{ paddingRight:40 }} />
      <button type="button" onClick={toggle}
        style={{ position:'absolute', right:12, top:'50%', transform:'translateY(-50%)', background:'none', border:'none', cursor:'pointer', color:visible?'#f0a500':'#94a3b8', transition:'color 0.2s', padding:2 }}>
        {visible
          ? <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
          : <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>}
      </button>
    </div>
  )
}

/* -- My Profile Tab ---------------------------------------------------- */
function MyProfile({ user, refreshUser }) {
  const [form, setForm] = useState({ full_name:user.full_name, department:user.department||'', phone:user.phone||'', avatar_color:user.avatar_color })
  const [pwForm, setPwForm] = useState({ current_password:'', new_password:'', confirm:'' })
  const [saving, setSaving]   = useState(false)
  const [pwSaving, setPwSaving] = useState(false)
  const [msg, setMsg]     = useState('')
  const [pwMsg, setPwMsg] = useState('')
  const [pwErr, setPwErr] = useState('')
  const f = (k,v) => setForm(p=>({...p,[k]:v}))

  const saveProfile = async () => {
    setSaving(true); setMsg('')
    try { await authApi.updateProfile(form); await refreshUser(); setMsg('✓ Profile saved') }
    catch(e) { setMsg('✗ ' + (e?.response?.data?.detail||'Failed')) }
    finally { setSaving(false) }
  }

  const savePassword = async () => {
    setPwErr(''); setPwMsg('')
    const { valid, rules } = validatePassword(pwForm.new_password)
    if (!valid) return setPwErr('Password needs: ' + rules.filter(r=>!r.ok).map(r=>r.label).join(', '))
    if (pwForm.new_password !== pwForm.confirm) return setPwErr('Passwords do not match')
    setPwSaving(true)
    try { await authApi.updateProfile({ current_password:pwForm.current_password, new_password:pwForm.new_password }); setPwForm({ current_password:'', new_password:'', confirm:'' }); setPwMsg('✓ Password updated') }
    catch(e) { setPwErr(e?.response?.data?.detail||'Failed') }
    finally { setPwSaving(false) }
  }

  const liveUser = { ...user, ...form }

  return (
    <div style={{ display:'grid', gridTemplateColumns:'340px 1fr', gap:20, alignItems:'start' }}>
      {/* Left */}
      <div style={{ display:'flex', flexDirection:'column', gap:16 }}>

        {/* Avatar card */}
        <div style={{ background:'white', borderRadius:20, overflow:'hidden', border:'1px solid #edf0f7', boxShadow:'0 2px 16px rgba(0,0,0,0.04)' }}>
          {/* colour band */}
          <div style={{ height:80, background:`linear-gradient(135deg, ${form.avatar_color}, ${shiftHue(form.avatar_color,40)})`, position:'relative' }}>
            <div style={{ position:'absolute', inset:0, background:'radial-gradient(circle at 30% 40%, rgba(255,255,255,0.2), transparent 60%)' }} />
          </div>
          <div style={{ padding:'0 24px 24px', marginTop:-36 }}>
            <AvatarGraphic user={liveUser} size={72} />
            <div style={{ marginTop:12, marginBottom:4, fontFamily:"'Fraunces',serif", fontSize:20, fontWeight:700, color:'var(--ink)' }}>{liveUser.full_name}</div>
            <div style={{ fontSize:13, color:'#94a3b8', marginBottom:10 }}>{user.email}</div>
            <RoleBadge role={user.role} />
          </div>
        </div>

        {/* Colour picker */}
        <div style={{ background:'white', borderRadius:16, padding:20, border:'1px solid #edf0f7' }}>
          <div style={{ fontSize:11.5, fontWeight:700, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:14 }}>Avatar Colour</div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:8 }}>
            {COLORS.map(c=>(
              <button key={c} onClick={()=>f('avatar_color',c)}
                style={{ width:'100%', aspectRatio:'1', borderRadius:10, background:c, border:'none', cursor:'pointer',
                  outline:form.avatar_color===c?`3px solid var(--ink)`:'3px solid transparent',
                  outlineOffset:2, transition:'all 0.15s', boxShadow:`0 3px 8px ${c}50` }}
                onMouseEnter={e=>e.target.style.transform='scale(1.12)'}
                onMouseLeave={e=>e.target.style.transform=''} />
            ))}
          </div>
          {/* live preview strip */}
          <div style={{ marginTop:16, display:'flex', alignItems:'center', gap:10, padding:'10px 14px', borderRadius:10, background:'#f8f9fc', border:'1px solid #edf0f7' }}>
            <AvatarGraphic user={liveUser} size={36} />
            <div>
              <div style={{ fontSize:13, fontWeight:600, color:'var(--ink)' }}>{liveUser.full_name||'Your Name'}</div>
              <div style={{ fontSize:11, color:'#94a3b8' }}>Preview</div>
            </div>
          </div>
        </div>

        {/* Account meta */}
        <div style={{ background:'white', borderRadius:16, padding:20, border:'1px solid #edf0f7' }}>
          <div style={{ fontSize:11.5, fontWeight:700, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:14 }}>Account</div>
          {[
            ['Status', <span style={{ fontSize:12, fontWeight:600, color:'#16a34a', display:'flex', alignItems:'center', gap:4 }}><span style={{ width:7,height:7,borderRadius:'50%',background:'#22c55e',display:'inline-block' }} />Active</span>],
            ['Role', <RoleBadge role={user.role} />],
            ['Member since', user.created_at ? new Date(user.created_at).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}) : '--'],
            ['Last login', user.last_login ? new Date(user.last_login).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '--'],
          ].map(([l,v])=>(
            <div key={l} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'9px 0', borderBottom:'1px solid #f8f9fc' }}>
              <span style={{ fontSize:12.5, color:'#64748b' }}>{l}</span>
              <span style={{ fontSize:12.5 }}>{v}</span>
            </div>
          ))}
        </div>

        {/* Tour replay */}
        <div style={{ background:'linear-gradient(135deg,#fffbeb,#fff7ed)', borderRadius:16, padding:20, border:'1px solid #fde68a', display:'flex', alignItems:'center', gap:14 }}>
          <div style={{ width:40, height:40, borderRadius:12, background:'linear-gradient(135deg,#f0a500,#e85d04)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:18, flexShrink:0, boxShadow:'0 4px 12px rgba(240,165,0,0.3)' }}>🎯</div>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:13, fontWeight:700, color:'#92400e', marginBottom:2 }}>Product Tour</div>
            <div style={{ fontSize:12, color:'#b45309' }}>Replay the walkthrough anytime</div>
          </div>
          <button onClick={() => { resetTour(user.id); if (tourBus.onLaunch) tourBus.onLaunch() }}
            style={{ padding:'8px 16px', borderRadius:10, border:'none', background:'linear-gradient(135deg,#f0a500,#e85d04)', color:'white', fontWeight:700, fontSize:12.5, cursor:'pointer', boxShadow:'0 4px 12px rgba(240,165,0,0.3)', whiteSpace:'nowrap' }}>
            Replay Tour
          </button>
        </div>
      </div>

      {/* Right */}
      <div style={{ display:'flex', flexDirection:'column', gap:16 }}>

        {/* Personal details */}
        <div style={{ background:'white', borderRadius:20, padding:28, border:'1px solid #edf0f7', boxShadow:'0 2px 16px rgba(0,0,0,0.04)' }}>
          <div style={{ fontSize:13, fontWeight:700, color:'var(--ink)', marginBottom:20 }}>Personal Details</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:16 }}>
            <div>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Full Name</label>
              <input className="input" value={form.full_name} onChange={e=>f('full_name',e.target.value)} placeholder="Your full name" />
            </div>
            <div>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Email</label>
              <input className="input" value={user.email} readOnly style={{ background:'#f8f9fc', color:'#94a3b8', cursor:'default' }} />
            </div>
            <div>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Department</label>
              <select className="select" value={form.department} onChange={e=>f('department',e.target.value)}>
                <option value="">-- Select --</option>
                {DEPTS.map(d=><option key={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Phone</label>
              <input className="input" value={form.phone} onChange={e=>f('phone',e.target.value)} placeholder="+91 98765 43210" />
            </div>
          </div>
          {msg&&<div style={{ marginBottom:14, padding:'9px 14px', borderRadius:8, background:msg.startsWith('✓')?'#f0fdf4':'#fef2f2', border:`1px solid ${msg.startsWith('✓')?'#bbf7d0':'#fecaca'}`, color:msg.startsWith('✓')?'#16a34a':'#dc2626', fontSize:13 }}>{msg}</div>}
          <button className="btn btn-accent" onClick={saveProfile} disabled={saving}>{saving?'Saving...':'Save Changes'}</button>
        </div>

        {/* Change password */}
        <div style={{ background:'white', borderRadius:20, padding:28, border:'1px solid #edf0f7', boxShadow:'0 2px 16px rgba(0,0,0,0.04)' }}>
          <div style={{ fontSize:13, fontWeight:700, color:'var(--ink)', marginBottom:4 }}>Change Password</div>
          <div style={{ fontSize:12.5, color:'#94a3b8', marginBottom:20 }}>Must be 8+ chars with one uppercase and one special character (. , @)</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14, marginBottom:8 }}>
            <div style={{ gridColumn:'1/-1' }}>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Current Password</label>
              <LightPasswordInput value={pwForm.current_password} onChange={e=>setPwForm(p=>({...p,current_password:e.target.value}))} />
            </div>
            <div>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>New Password</label>
              <LightPasswordInput value={pwForm.new_password} onChange={e=>setPwForm(p=>({...p,new_password:e.target.value}))} placeholder="8+ chars" />
              <PwStrength password={pwForm.new_password} />
            </div>
            <div style={{ gridColumn:'2/4' }}>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Confirm New Password</label>
              <LightPasswordInput value={pwForm.confirm} onChange={e=>setPwForm(p=>({...p,confirm:e.target.value}))} placeholder="Repeat" />
              {pwForm.confirm && pwForm.new_password!==pwForm.confirm && <div style={{ marginTop:5, fontSize:12, color:'#dc2626' }}>✗ Passwords do not match</div>}
              {pwForm.confirm && pwForm.new_password===pwForm.confirm && <div style={{ marginTop:5, fontSize:12, color:'#16a34a' }}>✓ Match</div>}
            </div>
          </div>
          {pwErr&&<div style={{ marginBottom:12, padding:'9px 14px', borderRadius:8, background:'#fef2f2', border:'1px solid #fecaca', color:'#dc2626', fontSize:13 }}>{pwErr}</div>}
          {pwMsg&&<div style={{ marginBottom:12, padding:'9px 14px', borderRadius:8, background:'#f0fdf4', border:'1px solid #bbf7d0', color:'#16a34a', fontSize:13 }}>{pwMsg}</div>}
          <button className="btn btn-accent" onClick={savePassword} disabled={pwSaving}>{pwSaving?'Updating...':'Update Password'}</button>
        </div>
      </div>
    </div>
  )
}

/* -- Reset Password Modal ---------------------------------------------- */
function ResetPwModal({ user, onClose, onDone }) {
  const [pw, setPw]         = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  const submit = async () => {
    setError('')
    if (pw.length < 6)  return setError('Password must be at least 6 characters')
    if (pw !== confirm) return setError('Passwords do not match')
    setSaving(true)
    try { await authApi.resetPassword(user.id, pw); onDone(user.email) }
    catch(e) { setError(e.response?.data?.detail || 'Reset failed') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ background:'white', borderRadius:16, padding:28, width:420,
      boxShadow:'0 20px 60px rgba(0,0,0,0.2)' }}>
      <div style={{ fontFamily:"'Fraunces',serif", fontSize:18, fontWeight:700,
        color:'var(--ink)', marginBottom:4 }}>Reset Password</div>
      <div style={{ fontSize:13, color:'#94a3b8', marginBottom:20 }}>
        New password for <strong style={{ color:'var(--ink)' }}>{user.full_name}</strong>
      </div>
      <div style={{ marginBottom:12 }}>
        <label style={{ fontSize:12.5, fontWeight:600, color:'var(--ink-2)', display:'block', marginBottom:5 }}>New Password</label>
        <input className="input" type="password" value={pw} onChange={e=>setPw(e.target.value)}
          placeholder="Min. 6 characters" autoFocus />
      </div>
      <div style={{ marginBottom:16 }}>
        <label style={{ fontSize:12.5, fontWeight:600, color:'var(--ink-2)', display:'block', marginBottom:5 }}>Confirm Password</label>
        <input className="input" type="password" value={confirm} onChange={e=>setConfirm(e.target.value)}
          placeholder="Repeat password" onKeyDown={e=>e.key==='Enter'&&submit()} />
      </div>
      {error && (
        <div style={{ background:'#fef2f2', border:'1px solid #fecaca', borderRadius:8,
          padding:'8px 12px', fontSize:13, color:'#dc2626', marginBottom:14 }}>{error}</div>
      )}
      <div style={{ display:'flex', gap:10, justifyContent:'flex-end' }}>
        <button className="btn btn-outline btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-sm" onClick={submit} disabled={saving}
          style={{ background:'#dc2626', color:'white', fontWeight:700 }}>
          {saving ? 'Resetting…' : 'Reset Password'}
        </button>
      </div>
    </div>
  )
}

/* -- Team & Roles Tab -------------------------------------------------- */
function TeamTab({ currentUser }) {
  const [users, setUsers]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(null)
  const [msg, setMsg]             = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newUser, setNewUser]     = useState({ full_name:'', email:'', password:'', role:'observer', department:'', phone:'' })
  const [creating, setCreating]   = useState(false)
  const [createErr, setCreateErr]   = useState('')
  const [resetTarget, setResetTarget] = useState(null)
  const nf = (k,v) => setNewUser(p=>({...p,[k]:v}))

  const load = () => { setLoading(true); authApi.listUsers().then(setUsers).finally(()=>setLoading(false)) }
  useEffect(()=>{ load() },[])

  const updateRole = async (u, role) => {
    setSaving(u.id); setMsg('')
    try { await authApi.updateUser(u.id,{role}); await load(); setMsg(`✓ ${u.full_name}'s role → ${ROLES[role]?.label}`) }
    catch(e) { setMsg('✗ '+(e?.response?.data?.detail||'failed')) }
    finally { setSaving(null) }
  }

  const toggleActive = async (u) => {
    setSaving(u.id)
    try { await authApi.updateUser(u.id,{is_active:u.is_active==='true'?'false':'true'}); await load() }
    catch(e) { setMsg('✗ '+(e?.response?.data?.detail||'failed')) }
    finally { setSaving(null) }
  }

  const createAccount = async (e) => {
    e.preventDefault(); setCreateErr('')
    const { valid, rules } = validatePassword(newUser.password)
    if (!valid) return setCreateErr('Password needs: '+rules.filter(r=>!r.ok).map(r=>r.label).join(', '))
    setCreating(true)
    try {
      await authApi.createUser(newUser)
      setNewUser({ full_name:'', email:'', password:'', role:'observer', department:'', phone:'' })
      setShowCreate(false); await load()
      setMsg('✓ Account created successfully')
    } catch(e) { setCreateErr(e?.response?.data?.detail||'Failed to create account') }
    finally { setCreating(false) }
  }

  const isSuperAdmin = currentUser.role === 'super_admin'

  return (
    <div>
      {/* Header row */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
        <div>
          <div style={{ fontSize:14, fontWeight:700, color:'var(--ink)' }}>Team Members</div>
          <div style={{ fontSize:12.5, color:'#94a3b8' }}>{users.length} users across all roles</div>
        </div>
        {isSuperAdmin && (
          <button className="btn btn-accent" onClick={()=>setShowCreate(p=>!p)}>
            {showCreate ? '✕ Cancel' : '+ Create Account'}
          </button>
        )}
      </div>

      {msg&&<div style={{ marginBottom:14, padding:'9px 16px', borderRadius:10, background:msg.startsWith('✓')?'#f0fdf4':'#fef2f2', border:`1px solid ${msg.startsWith('✓')?'#bbf7d0':'#fecaca'}`, color:msg.startsWith('✓')?'#16a34a':'#dc2626', fontSize:13 }}>{msg}</div>}

      {/* Create user form */}
      {showCreate && isSuperAdmin && (
        <div style={{ background:'white', borderRadius:20, padding:28, border:'2px dashed #e2e8f0', marginBottom:20, boxShadow:'0 4px 20px rgba(0,0,0,0.06)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:20 }}>
            <div style={{ width:36, height:36, borderRadius:10, background:'linear-gradient(135deg,#f0a500,#e85d04)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:16 }}>👤</div>
            <div>
              <div style={{ fontSize:14, fontWeight:700, color:'var(--ink)' }}>Create New Account</div>
              <div style={{ fontSize:12, color:'#94a3b8' }}>Super admin -- assign any role immediately</div>
            </div>
          </div>
          <form onSubmit={createAccount}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, marginBottom:14 }}>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Full Name *</label>
                <input className="input" required value={newUser.full_name} onChange={e=>nf('full_name',e.target.value)} placeholder="Jane Doe" />
              </div>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Work Email *</label>
                <input className="input" type="email" required value={newUser.email} onChange={e=>nf('email',e.target.value)} placeholder="jane@gatewaygroup.com" />
              </div>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Role *</label>
                <select className="select" value={newUser.role} onChange={e=>nf('role',e.target.value)}>
                  {Object.entries(ROLES).map(([k,v])=><option key={k} value={k}>{v.label}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Department</label>
                <select className="select" value={newUser.department} onChange={e=>nf('department',e.target.value)}>
                  <option value="">-- Select --</option>
                  {DEPTS.map(d=><option key={d}>{d}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Phone</label>
                <input className="input" value={newUser.phone} onChange={e=>nf('phone',e.target.value)} placeholder="+91 98765 43210" />
              </div>
              <div>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'#374151', marginBottom:6 }}>Temporary Password *</label>
                <LightPasswordInput value={newUser.password} onChange={e=>nf('password',e.target.value)} placeholder="Min 8 chars + A-Z + . , @" />
                <PwStrength password={newUser.password} />
              </div>
            </div>
            {createErr&&<div style={{ marginBottom:12, padding:'9px 14px', borderRadius:8, background:'#fef2f2', border:'1px solid #fecaca', color:'#dc2626', fontSize:13 }}>{createErr}</div>}
            <div style={{ display:'flex', gap:10 }}>
              <button type="button" onClick={()=>setShowCreate(false)} className="btn btn-outline">Cancel</button>
              <button type="submit" disabled={creating} className="btn btn-accent">{creating?'Creating...':'Create Account'}</button>
            </div>
          </form>
        </div>
      )}

      {/* Role legend */}
      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {Object.entries(ROLES).map(([k,v])=>(
          <div key={k} style={{ display:'flex', alignItems:'center', gap:6, padding:'4px 12px', borderRadius:20, background:v.bg, border:`1px solid ${v.color}25` }}>
            <div style={{ width:7, height:7, borderRadius:'50%', background:v.color }} />
            <span style={{ fontSize:11.5, fontWeight:600, color:v.color }}>{v.label}</span>
            <span style={{ fontSize:11, color:'#94a3b8' }}>({users.filter(u=>u.role===k).length})</span>
          </div>
        ))}
      </div>

      {loading ? <div style={{ padding:40, textAlign:'center' }}><Spinner /></div> : (
        <div style={{ display:'grid', gap:10 }}>
          {users.map(u=>{
            const ri  = ROLES[u.role]||ROLES.observer
            const isMe = u.id === currentUser.id
            return (
              <div key={u.id} style={{ background:'white', borderRadius:16, padding:'16px 20px', border:'1px solid #edf0f7',
                display:'flex', alignItems:'center', gap:16,
                opacity:u.is_active==='false'?0.55:1,
                transition:'all 0.2s',
                boxShadow:'0 1px 4px rgba(0,0,0,0.03)' }}
                onMouseEnter={e=>e.currentTarget.style.boxShadow='0 4px 16px rgba(0,0,0,0.08)'}
                onMouseLeave={e=>e.currentTarget.style.boxShadow='0 1px 4px rgba(0,0,0,0.03)'}>
                <AvatarGraphic user={u} size={44} />
                <div style={{ flex:1, minWidth:0 }}>
                  <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:2 }}>
                    <span style={{ fontWeight:600, fontSize:14.5, color:'var(--ink)' }}>{u.full_name}</span>
                    {isMe&&<span style={{ fontSize:10, fontWeight:700, padding:'1px 7px', borderRadius:20, background:'#f0fdf4', color:'#16a34a', border:'1px solid #bbf7d0' }}>YOU</span>}
                    {u.is_active==='false'&&<span style={{ fontSize:10, fontWeight:700, padding:'1px 7px', borderRadius:20, background:'#fef2f2', color:'#dc2626', border:'1px solid #fecaca' }}>INACTIVE</span>}
                  </div>
                  <div style={{ fontSize:12.5, color:'#94a3b8' }}>
                    {u.email}{u.department?` · ${u.department}`:''}{u.last_login?` · Last seen ${new Date(u.last_login).toLocaleDateString('en-IN',{day:'numeric',month:'short'})}` :''}
                  </div>
                </div>
                <div style={{ display:'flex', alignItems:'center', gap:10, flexShrink:0 }}>
                  {/* Role selector -- super admin only, not self */}
                  {isSuperAdmin && !isMe ? (
                    <select value={u.role} onChange={e=>updateRole(u,e.target.value)} disabled={saving===u.id}
                      style={{ fontSize:12, padding:'6px 12px', borderRadius:9, border:`1.5px solid ${ri.color}40`,
                        background:ri.bg, color:ri.color, fontWeight:700, cursor:'pointer', outline:'none', transition:'all 0.15s' }}>
                      {Object.entries(ROLES).map(([k,v])=><option key={k} value={k} style={{ background:'white', color:'var(--ink)' }}>{v.label}</option>)}
                    </select>
                  ) : (
                    <RoleBadge role={u.role} />
                  )}
                  {!isMe && canDo(currentUser.role,'admin') && (
                    <button onClick={()=>toggleActive(u)} disabled={saving===u.id}
                      style={{ fontSize:12, padding:'6px 14px', borderRadius:9, border:'1px solid #e2e8f0', background:'white',
                        cursor:'pointer', fontWeight:600, color:u.is_active==='true'?'#dc2626':'#16a34a', transition:'all 0.15s' }}
                      onMouseEnter={e=>{e.target.style.background=u.is_active==='true'?'#fef2f2':'#f0fdf4'}}
                      onMouseLeave={e=>{e.target.style.background='white'}}>
                      {saving===u.id?'...':u.is_active==='true'?'Deactivate':'Activate'}
                    </button>
                  )}
                  {!isMe && currentUser.role==='super_admin' && (
                    <button onClick={()=>setResetTarget(u)}
                      style={{ fontSize:12, padding:'6px 14px', borderRadius:9, border:'1px solid #e2e8f0',
                        background:'white', cursor:'pointer', fontWeight:600, color:'#64748b', transition:'all 0.15s' }}
                      onMouseEnter={e=>{e.target.style.background='#f8f9fc'; e.target.style.borderColor='#c4cad8'}}
                      onMouseLeave={e=>{e.target.style.background='white'; e.target.style.borderColor='#e2e8f0'}}>
                      🔑 Reset PW
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* -- Main Profile Page ------------------------------------------------- */
export default function Profile() {
  const { user, refreshUser, logout } = useAuth()
  const [tab, setTab] = useState('profile')

  if (!user) return <><Header title="Profile" /><div className="page-content"><Spinner /></div></>

  const tabs = [
    { id:'profile', label:'My Profile', icon:'👤' },
    ...(canDo(user.role,'admin') ? [{ id:'team', label:'Team & Roles', icon:'👥' }] : []),
  ]

  return (
    <>
      <Header title="Profile & Settings" subtitle={user.email} />
      <div className="page-content">

        {/* Hero banner */}
        <div style={{ background:'linear-gradient(135deg,#fff8e6 0%,#fef3cd 40%,#f0fdf4 100%)', borderRadius:24, padding:'28px 36px', marginBottom:24, display:'flex', alignItems:'center', gap:24, position:'relative', overflow:'hidden', border:'1px solid #fde68a' }}>
          <div style={{ position:'absolute', top:-60, right:-60, width:240, height:240, borderRadius:'50%', background:`radial-gradient(circle,${user.avatar_color}30,transparent 70%)`, pointerEvents:'none' }} />
          <div style={{ position:'absolute', bottom:-40, left:'30%', width:180, height:180, borderRadius:'50%', background:'radial-gradient(circle,rgba(59,130,246,0.08),transparent 70%)', pointerEvents:'none' }} />
          <AvatarGraphic user={user} size={76} />
          <div style={{ flex:1 }}>
            <div style={{ fontFamily:"'Fraunces',serif", fontSize:24, fontWeight:700, color:'white', marginBottom:4 }}>{user.full_name}</div>
            <div style={{ fontSize:13.5, color:'var(--ink-3)', marginBottom:10 }}>
              {user.email}{user.department?` · ${user.department}`:''}
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <RoleBadge role={user.role} />
              <span style={{ fontSize:12, color:'var(--ink-4)' }}>·</span>
              <span style={{ fontSize:12, color:'var(--ink-3)' }}>
                {user.last_login ? `Last login ${new Date(user.last_login).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}` : 'First session'}
              </span>
            </div>
          </div>
          {/* Stats */}
          <div style={{ display:'flex', gap:1, borderRadius:16, overflow:'hidden', border:'1px solid rgba(0,0,0,0.08)', background:'rgba(255,255,255,0.7)' }}>
            {[['Role Level', ROLES[user.role]?.level+'/4' || '-'],['Status','Active'],['Account','Verified']].map(([l,v],i)=>(
              <div key={l} style={{ padding:'14px 20px', background:'transparent', textAlign:'center', borderRight:i<2?'1px solid rgba(0,0,0,0.06)':undefined }}>
                <div style={{ fontFamily:"'Fraunces',serif", fontSize:17, fontWeight:700, color:'var(--ink)' }}>{v}</div>
                <div style={{ fontSize:10.5, color:'var(--ink-4)', marginTop:2, whiteSpace:'nowrap' }}>{l}</div>
              </div>
            ))}
          </div>
          <button onClick={logout}
            style={{ padding:'10px 20px', borderRadius:12, border:'1px solid var(--border)', background:'white', color:'var(--ink-3)', cursor:'pointer', fontSize:13, fontWeight:600, transition:'all 0.15s', whiteSpace:'nowrap' }}
            onMouseEnter={e=>{e.target.style.background='#fef2f2';e.target.style.borderColor='#fecaca';e.target.style.color='#dc2626'}}
            onMouseLeave={e=>{e.target.style.background='white';e.target.style.borderColor='var(--border)';e.target.style.color='var(--ink-3)'}}>
            Sign Out
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display:'flex', gap:4, marginBottom:24, background:'#f8f9fc', borderRadius:14, padding:4, width:'fit-content' }}>
          {tabs.map(t=>(
            <button key={t.id} onClick={()=>setTab(t.id)}
              style={{ display:'flex', alignItems:'center', gap:7, padding:'9px 20px', borderRadius:11, border:'none', cursor:'pointer', fontSize:13.5, fontWeight:600, transition:'all 0.2s',
                background:tab===t.id?'white':'transparent', color:tab===t.id?'var(--ink)':'var(--ink-4)',
                boxShadow:tab===t.id?'0 2px 10px rgba(0,0,0,0.08)':'none' }}>
              <span style={{ fontSize:15 }}>{t.icon}</span>{t.label}
            </button>
          ))}
        </div>

        {tab==='profile' && <MyProfile user={user} refreshUser={refreshUser} />}
        {tab==='team'    && <TeamTab currentUser={user} />}
      </div>
    </>
  )
}
