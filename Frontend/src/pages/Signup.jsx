import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import { validatePassword } from '../lib/auth'
import { PasswordInput } from './Login'

const DEPTS = ['Admin','Housekeeping','Maintenance','Finance','HR','Operations','Security','Procurement','IT','Management']

function PasswordStrength({ password }) {
  const { rules } = validatePassword(password)
  if (!password) return null
  return (
    <div style={{ marginTop:8, padding:'10px 14px', borderRadius:8, background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.08)' }}>
      {rules.map(r => (
        <div key={r.id} style={{ display:'flex', alignItems:'center', gap:8, marginBottom:r.id!=='special'?6:0 }}>
          <div style={{ width:16, height:16, borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
            background: r.ok ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.06)',
            border: `1px solid ${r.ok ? '#10b981' : 'rgba(255,255,255,0.12)'}`,
            transition:'all 0.2s' }}>
            {r.ok && <svg width="8" height="8" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5L8 3" stroke="#10b981" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
          </div>
          <span style={{ fontSize:12, color: r.ok ? '#6ee7b7' : 'rgba(255,255,255,0.35)', transition:'color 0.2s' }}>{r.label}</span>
        </div>
      ))}
    </div>
  )
}

export default function Signup() {
  const { signup } = useAuth()
  const navigate   = useNavigate()
  const [step, setStep]   = useState(1)
  const [form, setForm]   = useState({ full_name:'', email:'', password:'', confirm:'', department:'', phone:'' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const f = (k, v) => setForm(p => ({ ...p, [k]: v }))

  const nextStep = (e) => {
    e.preventDefault(); setError('')
    if (!form.full_name.trim()) return setError('Full name is required')
    if (!form.email.includes('@')) return setError('Enter a valid email')
    const { valid, rules } = validatePassword(form.password)
    if (!valid) return setError('Password does not meet requirements: ' + rules.filter(r=>!r.ok).map(r=>r.label).join(', '))
    if (form.password !== form.confirm) return setError('Passwords do not match')
    setStep(2)
  }

  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try { await signup({ full_name:form.full_name, email:form.email, password:form.password, department:form.department, phone:form.phone }); navigate('/') }
    catch(err) { setError(err?.response?.data?.detail || 'Could not create account'); setStep(1) }
    finally { setLoading(false) }
  }

  const inputStyle = { width:'100%', padding:'12px 16px', borderRadius:10, boxSizing:'border-box', background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.1)', color:'white', fontSize:14, outline:'none', transition:'all 0.15s' }
  const labelStyle = { display:'block', fontSize:12, fontWeight:600, color:'rgba(255,255,255,0.5)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }
  const onFocus = e => { e.target.style.borderColor='#f0a500'; e.target.style.boxShadow='0 0 0 3px rgba(240,165,0,0.15)' }
  const onBlur  = e => { e.target.style.borderColor='rgba(255,255,255,0.1)'; e.target.style.boxShadow='none' }

  return (
    <div className="auth-screen" style={{ minHeight:'100vh', display:'flex', background:'linear-gradient(135deg,#0d0f1a,#1a1f35,#0d1520)', fontFamily:"'DM Sans',sans-serif" }}>
      <div className="auth-brand-panel" style={{ flex:1, display:'flex', flexDirection:'column', justifyContent:'center', padding:'60px 80px', position:'relative', overflow:'hidden' }}>
        <div style={{ position:'absolute', top:-120, left:-120, width:400, height:400, borderRadius:'50%', background:'radial-gradient(circle,rgba(240,165,0,0.08),transparent 70%)', pointerEvents:'none' }} />
        <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:64 }}>
          <div style={{ width:44, height:44, borderRadius:12, background:'linear-gradient(135deg,#f0a500,#e85d04)', display:'flex', alignItems:'center', justifyContent:'center', color:'white', fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:20, boxShadow:'0 8px 24px rgba(240,165,0,0.35)' }}>G</div>
          <div>
            <div style={{ color:'white', fontWeight:700, fontSize:17 }}>Gateway Group</div>
            <div style={{ color:'rgba(255,255,255,0.35)', fontSize:11.5, textTransform:'uppercase', letterSpacing:'0.04em' }}>Inventory OS</div>
          </div>
        </div>
        <div style={{ maxWidth:420 }}>
          <div style={{ fontFamily:"'Fraunces',serif", fontSize:38, fontWeight:700, color:'white', lineHeight:1.2, marginBottom:20 }}>Join your team<br /><span style={{ color:'#f0a500' }}>on the platform.</span></div>
          <div style={{ color:'rgba(255,255,255,0.4)', fontSize:15, lineHeight:1.7, marginBottom:36 }}>Create your account to access procurement workflows and inventory analytics.</div>
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {[{role:'Observer',desc:'View-only access',color:'#64748b'},{role:'Analyst',desc:'View + export + reports',color:'#3b82f6'},{role:'Admin',desc:'Create, edit and approve',color:'#f59e0b'},{role:'Super Admin',desc:'Full access + user management',color:'#dc2626'}].map(r=>(
              <div key={r.role} style={{ display:'flex', alignItems:'center', gap:10 }}>
                <div style={{ width:8, height:8, borderRadius:'50%', background:r.color, flexShrink:0 }} />
                <span style={{ color:'rgba(255,255,255,0.6)', fontSize:13 }}><strong style={{ color:r.color }}>{r.role}</strong> -- {r.desc}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop:14, fontSize:12, color:'rgba(255,255,255,0.25)', lineHeight:1.6 }}>ℹ️ New self-signup accounts start as Observer. An admin can upgrade your role.</div>
        </div>
      </div>

      <div className="auth-form-panel" style={{ width:480, display:'flex', alignItems:'center', justifyContent:'center', padding:'40px 48px', background:'rgba(255,255,255,0.03)', borderLeft:'1px solid rgba(255,255,255,0.06)', backdropFilter:'blur(20px)' }}>
        <div className="auth-form-inner" style={{ width:'100%', maxWidth:360 }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:32 }}>
            {[1,2].map(s=>(
              <div key={s} style={{ display:'flex', alignItems:'center', gap:8 }}>
                <div style={{ width:28, height:28, borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center', background:step>=s?'linear-gradient(135deg,#f0a500,#e85d04)':'rgba(255,255,255,0.08)', color:step>=s?'white':'rgba(255,255,255,0.3)', fontSize:12, fontWeight:700, transition:'all 0.3s' }}>{s}</div>
                <span style={{ fontSize:12, color:step>=s?'rgba(255,255,255,0.7)':'rgba(255,255,255,0.25)', fontWeight:step===s?600:400 }}>{s===1?'Account':'Profile'}</span>
                {s<2&&<div style={{ width:32, height:1, background:step>s?'#f0a500':'rgba(255,255,255,0.12)' }} />}
              </div>
            ))}
          </div>

          {step===1&&(
            <>
              <div style={{ marginBottom:28 }}>
                <div style={{ fontFamily:"'Fraunces',serif", fontSize:24, fontWeight:700, color:'white', marginBottom:6 }}>Create account</div>
                <div style={{ color:'rgba(255,255,255,0.4)', fontSize:13.5 }}>Step 1 of 2 -- Your login details</div>
              </div>
              <form onSubmit={nextStep}>
                <div style={{ marginBottom:16 }}><label style={labelStyle}>Full Name</label><input type="text" required style={inputStyle} value={form.full_name} onChange={e=>f('full_name',e.target.value)} placeholder="Iman Mohiuddin" onFocus={onFocus} onBlur={onBlur} /></div>
                <div style={{ marginBottom:16 }}><label style={labelStyle}>Work Email</label><input type="email" required style={inputStyle} value={form.email} onChange={e=>f('email',e.target.value)} placeholder="you@gatewaygroup.com" onFocus={onFocus} onBlur={onBlur} /></div>
                <div style={{ marginBottom:4 }}>
                  <label style={labelStyle}>Password</label>
                  <PasswordInput value={form.password} onChange={e=>f('password',e.target.value)} placeholder="Min. 8 chars + uppercase + . , @" />
                  <PasswordStrength password={form.password} />
                </div>
                <div style={{ marginBottom:16, marginTop:12 }}>
                  <label style={labelStyle}>Confirm Password</label>
                  <PasswordInput value={form.confirm} onChange={e=>f('confirm',e.target.value)} placeholder="Repeat password" />
                  {form.confirm && form.password !== form.confirm && <div style={{ marginTop:6, fontSize:12, color:'#fca5a5' }}>✗ Passwords do not match</div>}
                  {form.confirm && form.password === form.confirm && form.confirm.length>0 && <div style={{ marginTop:6, fontSize:12, color:'#6ee7b7' }}>✓ Passwords match</div>}
                </div>
                {error&&<div style={{ marginBottom:14, padding:'10px 14px', borderRadius:8, background:'rgba(239,68,68,0.12)', border:'1px solid rgba(239,68,68,0.25)', color:'#fca5a5', fontSize:13 }}>{error}</div>}
                <button type="submit" style={{ width:'100%', padding:'13px', borderRadius:10, border:'none', cursor:'pointer', background:'linear-gradient(135deg,#f0a500,#e85d04)', color:'white', fontWeight:700, fontSize:15, boxShadow:'0 8px 24px rgba(240,165,0,0.35)' }}>Continue →</button>
              </form>
            </>
          )}

          {step===2&&(
            <>
              <div style={{ marginBottom:28 }}>
                <div style={{ fontFamily:"'Fraunces',serif", fontSize:24, fontWeight:700, color:'white', marginBottom:6 }}>Your profile</div>
                <div style={{ color:'rgba(255,255,255,0.4)', fontSize:13.5 }}>Step 2 of 2 -- Optional details</div>
              </div>
              <form onSubmit={submit}>
                <div style={{ marginBottom:16 }}>
                  <label style={labelStyle}>Department</label>
                  <select style={{ ...inputStyle, cursor:'pointer' }} value={form.department} onChange={e=>f('department',e.target.value)} onFocus={onFocus} onBlur={onBlur}>
                    <option value="">-- Select department --</option>
                    {DEPTS.map(d=><option key={d} value={d} style={{ background:'#1a1f35' }}>{d}</option>)}
                  </select>
                </div>
                <div style={{ marginBottom:24 }}><label style={labelStyle}>Phone (optional)</label><input type="tel" style={inputStyle} value={form.phone} onChange={e=>f('phone',e.target.value)} placeholder="+91 98765 43210" onFocus={onFocus} onBlur={onBlur} /></div>
                {error&&<div style={{ marginBottom:14, padding:'10px 14px', borderRadius:8, background:'rgba(239,68,68,0.12)', border:'1px solid rgba(239,68,68,0.25)', color:'#fca5a5', fontSize:13 }}>{error}</div>}
                <div style={{ display:'flex', gap:10 }}>
                  <button type="button" onClick={()=>setStep(1)} style={{ flex:1, padding:'13px', borderRadius:10, border:'1px solid rgba(255,255,255,0.15)', cursor:'pointer', background:'transparent', color:'rgba(255,255,255,0.6)', fontWeight:600, fontSize:14 }}>← Back</button>
                  <button type="submit" disabled={loading} style={{ flex:2, padding:'13px', borderRadius:10, border:'none', cursor:'pointer', background:loading?'rgba(240,165,0,0.5)':'linear-gradient(135deg,#f0a500,#e85d04)', color:'white', fontWeight:700, fontSize:15, boxShadow:loading?'none':'0 8px 24px rgba(240,165,0,0.35)' }}>{loading?'Creating...':'Create Account'}</button>
                </div>
              </form>
            </>
          )}

          <div style={{ marginTop:28, textAlign:'center', fontSize:13.5, color:'rgba(255,255,255,0.35)' }}>
            Already have an account?{' '}<Link to="/login" style={{ color:'#f0a500', fontWeight:600, textDecoration:'none' }}>Sign in</Link>
          </div>
        </div>
      </div>
    </div>
  )
}