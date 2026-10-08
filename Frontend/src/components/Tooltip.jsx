import { useState } from 'react'

export default function Tooltip({ text, children }) {
  return (
    <div className="tooltip-wrap">
      {children}
      <span className="tooltip-icon">?</span>
      <div className="tooltip-box">{text}</div>
    </div>
  )
}
