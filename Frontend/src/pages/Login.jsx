import { useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'

export function PasswordInput({ value, onChange, placeholder, onFocusCb, onBlurCb }) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef(null)
  const toggle = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!visible) { setVisible(true); timerRef.current = setTimeout(() => setVisible(false), 2000) }
    else setVisible(false)
  }
  return (
    <div style={{ position:'relative' }}>
      <input type={visible?'text':'password'} value={value} onChange={onChange} placeholder={placeholder||'••••••••'}
        style={{ width:'100%', padding:'12px 44px 12px 16px', borderRadius:10, boxSizing:'border-box',
          background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.1)',
          color:'white', fontSize:14, outline:'none', transition:'all 0.15s' }}
        onFocus={e=>{ e.target.style.borderColor='#f0a500'; e.target.style.boxShadow='0 0 0 3px rgba(240,165,0,0.15)'; onFocusCb&&onFocusCb(e) }}
        onBlur={e=>{ e.target.style.borderColor='rgba(255,255,255,0.1)'; e.target.style.boxShadow='none'; onBlurCb&&onBlurCb(e) }} />
      <button type="button" onClick={toggle} title={visible?'Hides in 2s':'Show password'}
        style={{ position:'absolute', right:12, top:'50%', transform:'translateY(-50%)', background:'none', border:'none', cursor:'pointer', color:visible?'#f0a500':'rgba(255,255,255,0.35)', fontSize:15, transition:'color 0.2s', padding:2 }}>
        {visible
          ? <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
          : <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>}
      </button>
    </div>
  )
}

export default function Login() {
  const { login } = useAuth()
  const navigate  = useNavigate()
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try { await login(email, password); navigate('/') }
    catch(err) { setError(err?.response?.data?.detail || err?.message || 'Unable to sign in. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <div className="auth-screen" style={{ minHeight:'100vh', display:'flex', background:'linear-gradient(135deg,#0d0f1a 0%,#1a1f35 50%,#0d1520 100%)', fontFamily:"'DM Sans',sans-serif" }}>
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
          <div style={{ fontFamily:"'Fraunces',serif", fontSize:42, fontWeight:700, color:'white', lineHeight:1.15, marginBottom:20 }}>Manage smarter.<br /><span style={{ color:'#f0a500' }}>Move faster.</span></div>
          <div style={{ color:'rgba(255,255,255,0.45)', fontSize:15, lineHeight:1.7, marginBottom:48 }}>Complete procurement and inventory platform for Gateway Group.</div>
          {[['📦','Real-time stock register'],['🛒','End-to-end procurement'],['📊','Budget forecasting & analytics']].map(([ic,label])=>(
            <div key={label} style={{ display:'flex', alignItems:'center', gap:10, marginBottom:14 }}>
              <div style={{ width:32, height:32, borderRadius:8, background:'rgba(240,165,0,0.12)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:14 }}>{ic}</div>
              <span style={{ color:'rgba(255,255,255,0.55)', fontSize:13.5 }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="auth-form-panel" style={{ width:480, display:'flex', alignItems:'center', justifyContent:'center', padding:'40px 48px', background:'rgba(255,255,255,0.03)', borderLeft:'1px solid rgba(255,255,255,0.06)', backdropFilter:'blur(20px)' }}>
        <div className="auth-form-inner" style={{ width:'100%', maxWidth:360 }}>
          <div style={{ marginBottom:36 }}>
            <div style={{ fontFamily:"'Fraunces',serif", fontSize:28, fontWeight:700, color:'white', marginBottom:8 }}>Welcome back</div>
            <div style={{ color:'rgba(255,255,255,0.4)', fontSize:14 }}>Sign in to continue</div>
          </div>
          <form onSubmit={submit}>
            <div style={{ marginBottom:18 }}>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'rgba(255,255,255,0.5)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Email</label>
              <input type="email" required autoFocus value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@gatewaygroup.com"
                style={{ width:'100%', padding:'12px 16px', borderRadius:10, boxSizing:'border-box', background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.1)', color:'white', fontSize:14, outline:'none', transition:'all 0.15s' }}
                onFocus={e=>{e.target.style.borderColor='#f0a500';e.target.style.boxShadow='0 0 0 3px rgba(240,165,0,0.15)'}}
                onBlur={e=>{e.target.style.borderColor='rgba(255,255,255,0.1)';e.target.style.boxShadow='none'}} />
            </div>
            <div style={{ marginBottom:10 }}>
              <label style={{ display:'block', fontSize:12, fontWeight:600, color:'rgba(255,255,255,0.5)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Password</label>
              <PasswordInput value={password} onChange={e=>setPassword(e.target.value)} />
            </div>
            {error && <div style={{ marginBottom:16, padding:'10px 14px', borderRadius:8, background:'rgba(239,68,68,0.12)', border:'1px solid rgba(239,68,68,0.25)', color:'#fca5a5', fontSize:13 }}>{error}</div>}
            <button type="submit" disabled={loading}
              style={{ width:'100%', padding:'13px', borderRadius:10, border:'none', cursor:'pointer', background:loading?'rgba(240,165,0,0.5)':'linear-gradient(135deg,#f0a500,#e85d04)', color:'white', fontWeight:700, fontSize:15, marginTop:8, boxShadow:loading?'none':'0 8px 24px rgba(240,165,0,0.35)', transition:'all 0.2s' }}>
              {loading ? 'Signing in...' : 'Sign In →'}
            </button>
          </form>
          <div style={{ marginTop:28, textAlign:'center', fontSize:13.5, color:'rgba(255,255,255,0.35)' }}>
            Don't have an account?{' '}<Link to="/signup" style={{ color:'#f0a500', fontWeight:600, textDecoration:'none' }}>Request access</Link>
          </div>
        </div>
      </div>
    </div>
  )
}